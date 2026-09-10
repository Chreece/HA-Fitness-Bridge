"""Diagnostics for the optional Fitness Server bridge."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ALLOWED_SERVICE_DOMAINS, CONF_ENTITY_MIRROR_ENABLED


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return bounded non-secret bridge diagnostics."""
    del hass
    client = getattr(entry, "runtime_data", None)
    raw_domains = entry.options.get(
        CONF_ALLOWED_SERVICE_DOMAINS, entry.data.get(CONF_ALLOWED_SERVICE_DOMAINS, [])
    )
    domains = sorted(
        str(value).strip().lower()
        for value in (raw_domains if isinstance(raw_domains, list) else [])
        if str(value).strip()
    )[:64]
    mirror = {}
    if client is not None and hasattr(client, "mirror_entities"):
        rows = client.mirror_entities()
        mirror = {
            "entity_count": min(len(rows), 4096),
            "profile_count": len(
                {str(row.get("profile_id") or "") for row in rows.values() if row.get("profile_id")}
            ),
        }
    return {
        "connected": bool(getattr(client, "connected", False)),
        "entity_mirror_enabled": bool(
            entry.options.get(
                CONF_ENTITY_MIRROR_ENABLED, entry.data.get(CONF_ENTITY_MIRROR_ENABLED, True)
            )
        ),
        "allowed_service_domains": domains,
        "mirror": mirror,
        "secrets_included": False,
    }
