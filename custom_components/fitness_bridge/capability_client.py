"""Capability-advertising HA-Fitness bridge client.

The base client already enforces its configured service-domain allow-list. This
subclass makes that exact allow-list part of the authenticated bridge hello so
Fitness can hide HA-dependent admin options that the installed bridge cannot
actually execute.
"""
from __future__ import annotations

import asyncio

from aiohttp import ClientError, WSMsgType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import FitnessBridgeClient, PROTOCOL_VERSION, _LOGGER


class CapabilityAdvertisingFitnessBridgeClient(FitnessBridgeClient):
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
                    capabilities = ["states", "services", "events", "runtime_catalog", "cast_launch"]
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
                    self._mirror_entities.clear()
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
