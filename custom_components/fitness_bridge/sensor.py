"""Read-only Fitness Server sensor mirror for Home Assistant."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback



def _native_value(value: Any) -> str | int | float | None:
    raw = str(value if value not in (None, "") else STATE_UNKNOWN)
    if raw in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return raw
    if number.is_integer() and len(raw) < 18:
        return int(number)
    return number


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    client = entry.runtime_data
    known: dict[str, FitnessMirrorSensor] = {}

    @callback
    def refresh() -> None:
        rows = client.mirror_entities()
        new_ids = sorted(set(rows) - set(known))
        if new_ids:
            entities = [FitnessMirrorSensor(client, entity_id) for entity_id in new_ids]
            for entity in entities:
                known[entity.remote_entity_id] = entity
            async_add_entities(entities)
        for entity in tuple(known.values()):
            entity.async_refresh_from_client()

    entry.async_on_unload(client.add_mirror_listener(refresh))
    refresh()


class FitnessMirrorSensor(SensorEntity):
    """One read-only state whose source of truth remains Fitness Server."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, client, remote_entity_id: str) -> None:
        self.client = client
        self.remote_entity_id = str(remote_entity_id)
        self.entity_id = self.remote_entity_id
        self._attr_unique_id = f"fitness_server:{self.remote_entity_id}"

    def _row(self) -> dict[str, Any] | None:
        return self.client.mirror_entities().get(self.remote_entity_id)

    @property
    def available(self) -> bool:
        row = self._row()
        return bool(self.client.connected and row is not None and str(row.get("state") or "") != STATE_UNAVAILABLE)

    @property
    def name(self) -> str:
        row = self._row() or {}
        attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        return str(attrs.get("friendly_name") or self.remote_entity_id.split(".", 1)[-1].replace("_", " ").title())[:256]

    @property
    def native_value(self) -> str | int | float | None:
        row = self._row()
        return _native_value(row.get("state")) if row else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        row = self._row() or {}
        attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        value = str(attrs.get("unit_of_measurement") or "").strip()
        return value[:64] or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        row = self._row() or {}
        attrs = dict(row.get("attributes") or {}) if isinstance(row.get("attributes"), dict) else {}
        attrs.pop("friendly_name", None)
        attrs.pop("unit_of_measurement", None)
        return attrs

    @callback
    def async_refresh_from_client(self) -> None:
        if getattr(self, "_hass", None) is not None:
            self.async_write_ha_state()
