"""Home Assistant side of the Fitness standalone smart-home bridge."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import ipaddress
import json
import logging
import math
import re
import time
from typing import Any
import uuid

from aiohttp import ClientError, WSMsgType
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.core import EVENT_STATE_CHANGED, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_ALLOWED_SERVICE_DOMAINS

_LOGGER = logging.getLogger(__name__)
PROTOCOL_VERSION = 1
DASHCAST_APP_ID = "84912283"
DASHCAST_POST_LOAD_SETTLE = 0.8
_MIRROR_PROFILE_RE = re.compile(r"^[a-f0-9]{32}$")
_MIRROR_ENTITY_RE = re.compile(r"^sensor\.fitness_[a-z0-9_]+$")


def _json_safe(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> Any:
    if budget is None:
        budget = [10_000]
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:16_384]
    if depth >= 7:
        return str(value)[:512]
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:256]:
            result[str(key)[:256]] = _json_safe(item, depth=depth + 1, budget=budget)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item, depth=depth + 1, budget=budget) for item in list(value)[:512]]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)[:2048]


def _state_payload(state) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "entity_id": str(state.entity_id),
        "state": str(state.state),
        "attributes": _json_safe(dict(state.attributes)),
        "last_changed": state.last_changed.isoformat() if state.last_changed else "",
        "last_updated": state.last_updated.isoformat() if state.last_updated else "",
    }


def _area_id_for(hass: HomeAssistant, entity_id: str) -> str:
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entry = entity_registry.async_get(entity_id)
    if entry is None:
        return ""
    if getattr(entry, "area_id", None):
        return str(entry.area_id)
    device_id = getattr(entry, "device_id", None)
    if device_id:
        device = device_registry.async_get(device_id)
        if device is not None and getattr(device, "area_id", None):
            return str(device.area_id)
    return ""


def _runtime_catalog(hass: HomeAssistant) -> dict[str, Any]:
    """Build the small smart-home catalog Fitness is allowed to see."""
    ai_rows: list[dict[str, Any]] = []
    seen = set()
    for state in sorted(hass.states.async_all(), key=lambda item: item.entity_id):
        entity_id = str(state.entity_id or "")
        if not entity_id.startswith("ai_task.") or entity_id in seen:
            continue
        if str(state.state or "") == "unavailable":
            continue
        seen.add(entity_id)
        ai_rows.append({"id": entity_id, "entity_id": entity_id, "name": str(state.attributes.get("friendly_name") or getattr(state, "name", "") or entity_id)[:256], "state": str(state.state or "")[:64], "available": True})

    entity_registry = er.async_get(hass)
    tts_rows: list[dict[str, Any]] = []
    for state in sorted(hass.states.async_all("tts"), key=lambda item: item.entity_id):
        entity_id = str(state.entity_id or "")
        registry_entry = entity_registry.async_get(entity_id)
        if registry_entry is not None and registry_entry.disabled_by is not None:
            continue
        if str(state.state or "") == "unavailable":
            continue
        platform = str(getattr(registry_entry, "platform", "") or "")[:64] if registry_entry is not None else ""
        supported = state.attributes.get("supported_languages")
        supported_languages = [str(item)[:32] for item in list(supported or [])[:128] if str(item).strip()] if isinstance(supported, (list, tuple, set)) else []
        tts_rows.append({
            "id": entity_id, "entity_id": entity_id,
            "name": str(state.attributes.get("friendly_name") or getattr(state, "name", "") or entity_id)[:256],
            "platform": platform,
            "state": str(state.state or "")[:64], "available": True,
            "supported_languages": supported_languages,
        })

    media_rows: list[dict[str, Any]] = []
    music_rows: list[dict[str, Any]] = []
    cast_rows: list[dict[str, Any]] = []
    for state in sorted(hass.states.async_all("media_player"), key=lambda item: item.entity_id):
        entity_id = str(state.entity_id or "")
        registry_entry = entity_registry.async_get(entity_id)
        if registry_entry is not None and registry_entry.disabled_by is not None:
            continue
        state_name = str(state.state or "")
        available = state_name not in {"unavailable", "unknown"}
        if not available:
            continue
        try:
            features = int(state.attributes.get("supported_features", 0) or 0)
        except (TypeError, ValueError):
            features = 0
        if not features & int(MediaPlayerEntityFeature.PLAY_MEDIA):
            continue
        platform = str(getattr(registry_entry, "platform", "") or "") if registry_entry is not None else ""
        music_assistant = platform in {"music_assistant", "mass"} or bool(state.attributes.get("mass_player_type"))
        row = {
            "id": entity_id, "entity_id": entity_id,
            "name": str(state.attributes.get("friendly_name") or getattr(state, "name", "") or entity_id)[:256],
            "area_id": _area_id_for(hass, entity_id), "platform": platform[:64],
            "state": state_name[:64], "available": True,
        }
        media_rows.append(dict(row))
        music_rows.append({**row, "music_assistant": bool(music_assistant)})
        if registry_entry is not None and platform == "cast":
            cast_rows.append(dict(row))

    color_capable = {"hs", "xy", "rgb", "rgbw", "rgbww"}
    light_rows: list[dict[str, Any]] = []
    for state in sorted(hass.states.async_all("light"), key=lambda item: item.entity_id):
        if str(state.state or "") in {"unavailable", "unknown"}:
            continue
        entity_id = str(state.entity_id or "")
        registry_entry = entity_registry.async_get(entity_id)
        if registry_entry is not None and registry_entry.disabled_by is not None:
            continue
        modes = {str(getattr(mode, "value", mode)).lower() for mode in (state.attributes.get("supported_color_modes") or [])}
        if not modes.intersection(color_capable):
            continue
        light_rows.append({
            "id": entity_id, "entity_id": entity_id,
            "name": str(state.attributes.get("friendly_name") or getattr(state, "name", "") or entity_id)[:256],
            "area_id": _area_id_for(hass, entity_id), "state": str(state.state or "")[:64], "available": True,
        })

    areas = [{"id": str(area.id)[:128], "name": str(area.name)[:256]} for area in ar.async_get(hass).async_list_areas()]
    areas.sort(key=lambda row: str(row.get("name") or "").casefold())
    integrations, sensors = [], []
    fitness_domains = {"garmin_connect", "garmin", "polar", "fitbit", "withings", "oura", "whoop", "suunto", "strava", "health_connect", "apple_health"}
    for entry in hass.config_entries.async_entries():
        if entry.domain not in fitness_domains:
            continue
        integrations.append({"id": entry.entry_id, "name": str(entry.title)[:256], "platform": entry.domain})
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            if entity.disabled_by is not None or not entity.entity_id.startswith("sensor."):
                continue
            state = hass.states.get(entity.entity_id)
            if state is None:
                continue
            try:
                if not math.isfinite(float(state.state)):
                    continue
            except (TypeError, ValueError):
                continue
            sensors.append({"id": entity.entity_id, "entity_id": entity.entity_id,
                "integration_id": entry.entry_id, "name": str(state.attributes.get("friendly_name") or entity.entity_id)[:256],
                "unit": str(state.attributes.get("unit_of_measurement") or "")[:32], "available": True})
    return {
        "ai_entities": ai_rows[:512], "areas": areas[:1024],
        "tts_entities": tts_rows[:256], "tts_media_players": media_rows[:2048], "music_media_players": music_rows[:2048],
        "cast_media_players": cast_rows[:1024], "lights": light_rows[:4096],
        "integrations": integrations[:512], "integration_entities": sensors[:2048],
    }


def _cast_registry_entry(hass: HomeAssistant, entity_id: str):
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.disabled_by is not None or str(getattr(entry, "platform", "") or "") != "cast":
        raise ValueError("cast_target_not_available")
    state = hass.states.get(entity_id)
    if state is None or str(state.state or "") in {"unavailable", "unknown"}:
        raise ValueError("cast_target_not_available")
    return entry


def _ha_cast_runtime_info(hass: HomeAssistant, registry_entry, target_uuid: str):
    config_entry_id = str(getattr(registry_entry, "config_entry_id", "") or "")
    if not config_entry_id:
        return None
    config_entry = hass.config_entries.async_get_entry(config_entry_id)
    runtime_data = getattr(config_entry, "runtime_data", None) if config_entry is not None else None
    browser = getattr(runtime_data, "browser", None)
    devices = getattr(browser, "devices", None)
    if not isinstance(devices, dict):
        return None
    try:
        target_key = uuid.UUID(str(target_uuid))
    except (ValueError, TypeError, AttributeError):
        return None
    value = devices.get(target_key)
    if value is not None:
        return value
    for candidate in devices.values():
        if str(getattr(candidate, "uuid", "") or "") == str(target_key):
            return candidate
    return None


def _cast_runtime_direct_endpoint(cast_info) -> tuple[str, int] | None:
    candidates: list[tuple[tuple[int, int, int], str, int]] = []
    for service in tuple(getattr(cast_info, "services", None) or ()):
        host = str(getattr(service, "host", "") or "").strip().strip("[]")
        if not host:
            continue
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue
        if address.is_unspecified or address.is_multicast:
            continue
        try:
            port = int(getattr(service, "port", 8009) or 8009)
        except (TypeError, ValueError):
            port = 8009
        rank = (0 if address.version == 4 else 1, 0 if address.is_private else 1, 1 if address.is_link_local else 0)
        candidates.append((rank, str(address), port))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    _, host, port = candidates[0]
    return host, port


def _launch_dashcast_sync(target_uuid: str, url: str, cast_info, shared_zeroconf, direct_endpoint: tuple[str, int] | None) -> bool:
    try:
        import pychromecast
        from dataclasses import replace
        from pychromecast.controllers.dashcast import DashCastController
        from pychromecast.models import HostServiceInfo
    except ImportError:
        return False
    target = None
    try:
        if cast_info is None:
            return False
        if direct_endpoint is not None:
            host, port = direct_endpoint
            cast_info = replace(cast_info, services={HostServiceInfo(host, port)}, host=host, port=port)
            target = pychromecast.get_chromecast_from_cast_info(cast_info, None, tries=1, timeout=6.0)
        else:
            target = pychromecast.get_chromecast_from_cast_info(cast_info, shared_zeroconf, tries=1, timeout=6.0)
        target.wait(timeout=15)
        controller = DashCastController()
        target.register_handler(controller)
        for launch_round in range(2):
            controller.launch(force_launch=True)
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                app_id = str(getattr(target, "app_id", "") or "")
                namespaces = set(getattr(getattr(target, "status", None), "namespaces", None) or [])
                if app_id == DASHCAST_APP_ID and (controller.is_active or controller.namespace in namespaces):
                    controller.send_message_nocheck({"url": url, "force": True, "reload": False, "reload_time": 0}, inc_session_id=True)
                    time.sleep(DASHCAST_POST_LOAD_SETTLE)
                    return True
                time.sleep(0.15)
            app_id = str(getattr(target, "app_id", "") or "")
            namespaces = set(getattr(getattr(target, "status", None), "namespaces", None) or [])
            if launch_round == 0 and app_id == DASHCAST_APP_ID and controller.namespace not in namespaces:
                try:
                    target.quit_app()
                except Exception:
                    return False
                time.sleep(0.5)
                continue
            return False
        return False
    except Exception as err:
        _LOGGER.warning("Fitness bridge DashCast transport failed for %s: %s", target_uuid, err)
        return False
    finally:
        if target is not None:
            try:
                target.disconnect()
            except Exception:
                pass


async def _async_launch_dashcast(hass: HomeAssistant, registry_entry, url: str) -> bool:
    try:
        target_uuid = str(uuid.UUID(str(registry_entry.unique_id)))
    except (ValueError, TypeError, AttributeError):
        return False
    cast_info = _ha_cast_runtime_info(hass, registry_entry, target_uuid)
    if cast_info is None:
        return False
    direct_endpoint = _cast_runtime_direct_endpoint(cast_info)
    shared_zeroconf = None
    if direct_endpoint is None:
        try:
            from homeassistant.components import zeroconf as ha_zeroconf
            shared_zeroconf = await ha_zeroconf.async_get_instance(hass)
        except Exception:
            return False
    return await hass.async_add_executor_job(_launch_dashcast_sync, target_uuid, url, cast_info, shared_zeroconf, direct_endpoint)


async def _async_stop_dashcast(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    state = hass.states.get(entity_id)
    app_id = str(state.attributes.get("app_id") or "") if state is not None else ""
    if not app_id:
        return {"stopped": True, "already_idle": True, "entity_id": entity_id}
    if app_id != DASHCAST_APP_ID:
        return {"stopped": False, "reason": "foreign_cast_app", "entity_id": entity_id}
    if not hass.services.has_service("media_player", "turn_off"):
        return {"stopped": False, "reason": "media_player_turn_off_unavailable", "entity_id": entity_id}
    await hass.services.async_call("media_player", "turn_off", {}, target={"entity_id": entity_id}, blocking=True, return_response=False)
    return {"stopped": True, "entity_id": entity_id}


class FitnessBridgeClient:
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        url: str,
        token: str,
        allowed_service_domains: set[str] | None = None,
        entity_mirror_enabled: bool = True,
    ) -> None:
        self.hass = hass
        self.url = url
        self.token = token
        self.entity_mirror_enabled = bool(entity_mirror_enabled)
        self.allowed_service_domains = {
            str(value).strip().lower()
            for value in (allowed_service_domains or set(DEFAULT_ALLOWED_SERVICE_DOMAINS))
            if str(value).strip()
        }
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._ws = None
        self._send_lock = asyncio.Lock()
        self._subscriptions: set[str] = set()
        self._state_unsub: Callable[[], None] | None = None
        self._mirror_entities: dict[str, dict[str, Any]] = {}
        self._mirror_profile_entities: dict[str, set[str]] = {}
        self._mirror_listeners: set[Callable[[], None]] = set()
        self._fitness_playback: dict[str, tuple[str, str]] = {}

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    def mirror_entities(self) -> dict[str, dict[str, Any]]:
        return {entity_id: dict(row) for entity_id, row in self._mirror_entities.items()}

    def add_mirror_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._mirror_listeners.add(listener)
        def unsubscribe() -> None:
            self._mirror_listeners.discard(listener)
        return unsubscribe

    def _notify_mirror_listeners(self) -> None:
        for listener in tuple(self._mirror_listeners):
            try:
                listener()
            except Exception:
                continue

    def _publish_mirror(self, profile_id: str, entities: Any, *, replace: bool) -> dict[str, Any]:
        if not self.entity_mirror_enabled:
            raise PermissionError("Fitness entity mirroring is disabled")
        profile_id = str(profile_id or "").strip().lower()
        if not _MIRROR_PROFILE_RE.fullmatch(profile_id):
            raise ValueError("invalid mirror profile id")
        prefix = f"sensor.fitness_{profile_id}_"
        rows = entities if isinstance(entities, list) else []
        if len(rows) > 256:
            raise ValueError("too many mirrored entities")
        new_ids: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            entity_id = str(raw.get("entity_id") or "").strip().lower()
            if not entity_id.startswith(prefix) or not _MIRROR_ENTITY_RE.fullmatch(entity_id):
                raise ValueError("invalid mirrored entity id")
            state = str(raw.get("state") if raw.get("state") not in (None, "") else "unknown")[:255]
            attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
            clean_attrs = _json_safe(attrs)
            if not isinstance(clean_attrs, dict):
                clean_attrs = {}
            clean_attrs["fitness_profile_id"] = profile_id
            clean_attrs["fitness_source"] = "fitness_server"
            self._mirror_entities[entity_id] = {
                "entity_id": entity_id, "state": state, "attributes": clean_attrs,
                "profile_id": profile_id,
            }
            new_ids.add(entity_id)
        previous = self._mirror_profile_entities.get(profile_id, set())
        removed = 0
        if replace:
            for entity_id in previous - new_ids:
                self._mirror_entities.pop(entity_id, None)
                removed += 1
            self._mirror_profile_entities[profile_id] = set(new_ids)
        else:
            self._mirror_profile_entities.setdefault(profile_id, set()).update(new_ids)
        self._notify_mirror_listeners()
        return {"profile_id": profile_id, "published": len(new_ids), "removed": removed}

    def _clear_mirror(self, profile_id: str) -> dict[str, Any]:
        profile_id = str(profile_id or "").strip().lower()
        if not _MIRROR_PROFILE_RE.fullmatch(profile_id):
            raise ValueError("invalid mirror profile id")
        entity_ids = self._mirror_profile_entities.pop(profile_id, set())
        for entity_id in entity_ids:
            self._mirror_entities.pop(entity_id, None)
        self._notify_mirror_listeners()
        return {"profile_id": profile_id, "cleared": True, "removed": len(entity_ids)}

    async def async_start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = self.hass.async_create_background_task(
            self._run(), "fitness_server_bridge"
        )

    async def async_stop(self) -> None:
        self._stop.set()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._remove_state_listener()

    async def _run(self) -> None:
        delay = 1.0
        session = async_get_clientsession(self.hass)
        while not self._stop.is_set():
            try:
                async with session.ws_connect(
                    self.url,
                    heartbeat=30,
                    max_msg_size=4 * 1024 * 1024,
                    autoclose=True,
                ) as ws:
                    self._ws = ws
                    capabilities = ["states", "services", "events", "runtime_catalog", "cast_launch", "media_source", "integration_read"]
                    # Advertise the implemented transport operation even if HA
                    # is still starting integrations. The live catalog below
                    # gates readiness and can recover without reconnecting.
                    if "ai_task" in self.allowed_service_domains:
                        capabilities.append("ai_task")
                    if self.entity_mirror_enabled:
                        capabilities.append("entity_mirror")
                    await ws.send_json(
                        {
                            "type": "bridge/hello",
                            "protocol": PROTOCOL_VERSION,
                            "instance_id": str(getattr(self.hass, "instance_id", "") or "home-assistant"),
                            "capabilities": capabilities,
                            "service_domains": sorted(self.allowed_service_domains),
                            "token": self.token,
                        }
                    )
                    hello = await asyncio.wait_for(ws.receive(), timeout=10)
                    if hello.type != WSMsgType.TEXT:
                        raise RuntimeError("Fitness bridge handshake failed")
                    payload = hello.json()
                    if payload.get("type") != "bridge/hello/ok":
                        raise RuntimeError("Fitness bridge rejected the connection")
                    delay = 1.0
                    _LOGGER.info("Connected to standalone Fitness server")
                    # Every bridge session starts with an empty mirror generation.
                    # Fitness will republish the authoritative active profiles; this
                    # prevents a profile deleted while disconnected from reappearing
                    # from stale HA-side memory after reconnect.
                    self._mirror_entities.clear()
                    self._fitness_playback.clear()
                    self._mirror_profile_entities.clear()
                    self._notify_mirror_listeners()
                    async for message in ws:
                        if message.type == WSMsgType.TEXT:
                            try:
                                request = message.json()
                            except Exception:
                                continue
                            if isinstance(request, dict) and request.get("type") == "bridge/request":
                                self.hass.async_create_task(self._handle_request(request))
                        elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                            break
            except asyncio.CancelledError:
                raise
            except (ClientError, OSError, RuntimeError, asyncio.TimeoutError) as err:
                if not self._stop.is_set():
                    _LOGGER.debug("Fitness server bridge disconnected: %s", err)
            finally:
                self._ws = None
                self._remove_state_listener()
                self._notify_mirror_listeners()
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2.0, 30.0)

    async def _send_json(self, payload: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            return
        async with self._send_lock:
            await ws.send_json(_json_safe(payload))

    async def _handle_request(self, request: dict[str, Any]) -> None:
        request_id = str(request.get("id") or "")
        operation = str(request.get("operation") or "")
        try:
            if operation == "state/get":
                entity_id = str(request.get("entity_id") or "").strip()
                result = _state_payload(self.hass.states.get(entity_id))
            elif operation == "state/list":
                domain = str(request.get("domain") or "").strip().lower()
                states = self.hass.states.async_all()
                if domain:
                    states = [state for state in states if state.entity_id.split(".", 1)[0] == domain]
                result = [_state_payload(state) for state in states[:10_000]]
            elif operation == "state/subscribe":
                entity_ids = {
                    str(value).strip()
                    for value in (request.get("entity_ids") or [])
                    if isinstance(value, str) and "." in value
                }
                self._subscriptions = set(list(entity_ids)[:4096])
                self._ensure_state_listener()
                result = {"subscribed": sorted(self._subscriptions)}
            elif operation == "catalog/runtime":
                result = _runtime_catalog(self.hass)
                if not self.hass.services.has_service("ai_task", "generate_data"):
                    result["ai_entities"] = []
                result["music_providers"] = await self._music_sources()
            elif operation == "ai/generate":
                entity_id = str(request.get("entity_id") or "")
                instructions = str(request.get("instructions") or "")
                if "ai_task" not in self.allowed_service_domains or not entity_id.startswith("ai_task."):
                    raise PermissionError("AI task service is not allowed")
                if not self.hass.states.get(entity_id) or not 1 <= len(instructions) <= 8000:
                    raise ValueError("Invalid AI task")
                result = await self.hass.services.async_call("ai_task", "generate_data", {
                    "entity_id": entity_id, "task_name": "Fitness user request", "instructions": instructions,
                }, blocking=True, return_response=True)
            elif operation == "integration/read":
                ids = request.get("entity_ids") or []
                if not isinstance(ids, list) or len(ids) > 256:
                    raise ValueError("Invalid sensor selection")
                known = {x["id"]: x for x in _runtime_catalog(self.hass)["integration_entities"]}
                if any(x not in known for x in ids):
                    raise PermissionError("Not a supported fitness integration sensor")
                result = {"sensors": [{"id": x, "name": known[x]["name"], "unit": known[x]["unit"],
                    "value": float(self.hass.states.get(x).state)} for x in ids]}
            elif operation in {"media/browse", "media/play", "media/move"}:
                result = await self._media_operation(operation, request)
            elif operation == "cast/launch_url":
                entity_id = str(request.get("entity_id") or "").strip().lower()
                url = str(request.get("url") or "").strip()
                if not url.startswith(("http://", "https://")) or len(url) > 4096:
                    raise ValueError("invalid_cast_url")
                entry = _cast_registry_entry(self.hass, entity_id)
                launched = await _async_launch_dashcast(self.hass, entry, url)
                result = {"launched": bool(launched), "entity_id": entity_id, "transport": "ha_cast_runtime_dashcast"}
            elif operation == "cast/stop":
                entity_id = str(request.get("entity_id") or "").strip().lower()
                _cast_registry_entry(self.hass, entity_id)
                result = await _async_stop_dashcast(self.hass, entity_id)
            elif operation == "entities/publish":
                result = self._publish_mirror(
                    str(request.get("profile_id") or ""),
                    request.get("entities"),
                    replace=bool(request.get("replace", True)),
                )
            elif operation == "entities/clear":
                if not self.entity_mirror_enabled:
                    raise PermissionError("Fitness entity mirroring is disabled")
                result = self._clear_mirror(str(request.get("profile_id") or ""))
            elif operation == "service/call":
                domain = str(request.get("domain") or "").strip().lower()
                service = str(request.get("service") or "").strip()
                if domain not in self.allowed_service_domains:
                    raise PermissionError(f"service domain not allowed: {domain}")
                if not service or not self.hass.services.has_service(domain, service):
                    raise ValueError(f"service not found: {domain}.{service}")
                data = request.get("data") if isinstance(request.get("data"), dict) else {}
                target = request.get("target") if isinstance(request.get("target"), dict) else {}
                result = await self.hass.services.async_call(
                    domain,
                    service,
                    dict(data),
                    target=dict(target) or None,
                    blocking=True,
                    return_response=False,
                )
            else:
                raise ValueError(f"unsupported bridge operation: {operation}")
            response = {
                "type": "bridge/response",
                "id": request_id,
                "success": True,
                "result": _json_safe(result),
            }
        except Exception as err:
            response = {
                "type": "bridge/response",
                "id": request_id,
                "success": False,
                "error": str(err)[:1024],
            }
        await self._send_json(response)

    async def _music_sources(self):
        from homeassistant.components import media_source
        try:
            root = await media_source.async_browse_media(self.hass, None)
        except Exception:
            return []
        rows = []
        for child in (root.children or [])[:128]:
            ident = str(child.media_content_id or "")
            if ident.startswith("media-source://") and not ident.startswith(("media-source://camera", "media-source://tts")):
                rows.append({"id": ident, "name": str(child.title)[:256], "available": True})
        return rows

    async def _media_operation(self, operation, request):
        from homeassistant.components import media_source
        provider, ident = str(request.get("provider") or ""), str(request.get("media_id") or "")
        sources = {row["id"] for row in await self._music_sources()}
        if (provider not in sources or len(ident) > 2048 or "?" in ident or "#" in ident
                or not (ident == provider or ident.startswith(provider.rstrip("/") + "/"))):
            raise PermissionError("Invalid music source")
        if operation == "media/browse":
            item = await media_source.async_browse_media(self.hass, ident)
            def row(child):
                child_id = str(child.media_content_id or "")
                if not (child_id == provider or child_id.startswith(provider.rstrip("/") + "/")):
                    return None
                playable = bool(child.can_play and (str(child.media_content_type).startswith("audio/") or str(child.media_content_type) in {"music", "application/ogg"}))
                if not child.can_expand and not playable:
                    return None
                return {"id": child_id[:2048], "name": str(child.title)[:256], "can_expand": bool(child.can_expand), "can_play": playable}
            return {"id": ident, "name": str(item.title)[:256], "items": [r for child in (item.children or [])[:256] if (r := row(child))]}
        if "media_player" not in self.allowed_service_domains:
            raise PermissionError("Media player service is not allowed")
        entity_id = str(request.get("entity_id") or "")
        players = {x["id"] for x in _runtime_catalog(self.hass)["music_media_players"]}
        if operation == "media/move":
            previous = str(request.get("from_entity_id") or "")
            tracked = self._fitness_playback.get(previous)
            state = self.hass.states.get(previous)
            if (previous not in players or not tracked or tracked[0] != ident or state is None
                    or state.state != "playing" or state.attributes.get("media_content_id") not in tracked):
                return {"moved": False, "reason": "previous_playback_not_owned"}
            if entity_id and entity_id not in players:
                raise ValueError("Invalid music player")
            await self.hass.services.async_call("media_player", "media_stop", {}, target={"entity_id": previous}, blocking=True)
            self._fitness_playback.pop(previous, None)
            if not entity_id:
                return {"moved": False, "stopped": True}
        if entity_id not in players:
            raise ValueError("Invalid music player")
        resolved = await media_source.async_resolve_media(self.hass, ident, entity_id)
        if not str(resolved.mime_type).startswith("audio/") and resolved.mime_type != "application/ogg":
            raise PermissionError("Only audio is supported")
        # Keep resolved URLs (which may contain provider tokens) on HA. Pass the
        # media-source identifier to HA's player so its integration resolves it.
        await self.hass.services.async_call("media_player", "play_media", {
            "media_content_id": ident, "media_content_type": resolved.mime_type,
        }, target={"entity_id": entity_id}, blocking=True)
        self._fitness_playback[entity_id] = (ident, str(resolved.url))
        return {"playing": True, **({"moved": True} if operation == "media/move" else {})}

    def _ensure_state_listener(self) -> None:
        if self._state_unsub is not None or not self._subscriptions:
            return

        @callback
        def state_changed(event) -> None:
            entity_id = str(event.data.get("entity_id") or "")
            if entity_id not in self._subscriptions:
                return
            state = event.data.get("new_state")
            self.hass.async_create_task(
                self._send_json(
                    {
                        "type": "bridge/event",
                        "event": "state_changed",
                        "state": _state_payload(state),
                    }
                )
            )

        self._state_unsub = self.hass.bus.async_listen(EVENT_STATE_CHANGED, state_changed)

    def _remove_state_listener(self) -> None:
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
