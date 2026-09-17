"""Optional Home Assistant bridge for standalone Fitness Server."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .client import FitnessBridgeClient
from .pairing import register_pairing
from .const import (
    CONF_ALLOWED_SERVICE_DOMAINS,
    CONF_BRIDGE_TOKEN,
    CONF_ENTITY_MIRROR_ENABLED,
    CONF_SERVER_WS_URL,
    DEFAULT_ALLOWED_SERVICE_DOMAINS,
    DEFAULT_ENTITY_MIRROR_ENABLED,
    DOMAIN,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the local pairing surface used by the config entry flow."""
    register_pairing(hass)
    return True


def _client_from_entry(hass: HomeAssistant, entry: ConfigEntry) -> FitnessBridgeClient:
    raw_domains = entry.options.get(
        CONF_ALLOWED_SERVICE_DOMAINS,
        entry.data.get(CONF_ALLOWED_SERVICE_DOMAINS, list(DEFAULT_ALLOWED_SERVICE_DOMAINS)),
    )
    domains = {
        str(value).strip().lower()
        for value in (raw_domains if isinstance(raw_domains, list) else DEFAULT_ALLOWED_SERVICE_DOMAINS)
        if str(value).strip()
    }
    return FitnessBridgeClient(
        hass,
        url=str(entry.data.get(CONF_SERVER_WS_URL) or ""),
        token=str(entry.data.get(CONF_BRIDGE_TOKEN) or ""),
        allowed_service_domains=domains,
        entity_mirror_enabled=bool(
            entry.options.get(
                CONF_ENTITY_MIRROR_ENABLED,
                entry.data.get(CONF_ENTITY_MIRROR_ENABLED, DEFAULT_ENTITY_MIRROR_ENABLED),
            )
        ),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one outbound bridge connection.

    Fitness Server remains authoritative. Loading this config entry must not
    require Fitness Server to be reachable: the client reconnects in the
    background and mirrored entities simply remain unavailable meanwhile.
    """
    client = _client_from_entry(hass, entry)
    entry.runtime_data = client
    try:
        register_pairing(hass)
        if entry.data.get(CONF_SERVER_WS_URL):
            await client.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    except Exception:
        await client.async_stop()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload bridge platforms, then stop the outbound bridge client."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if not unload_ok:
        return False
    client = getattr(entry, "runtime_data", None)
    if client is not None:
        await client.async_stop()
    return True
