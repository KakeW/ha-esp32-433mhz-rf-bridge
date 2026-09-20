"""Sensor platform for ESP32 433 MHz RF Bridge."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROTOCOL_HARJU
from .hub import ESP32RFBridgeHub
from .store import SwitchRecord


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ESP32RFBridgeHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESP32 433 MHz RF Bridge sensor entities."""

    hub = entry.runtime_data
    known_ids = set(hub.store.records)
    entities: list[SensorEntity] = [
        HubStatusSensor(
            hub,
            key="learning_status",
            name="Learning status",
            value_getter=lambda: hub.learning_status,
        ),
        HubStatusSensor(
            hub,
            key="last_received_code",
            name="Last received RF code",
            value_getter=lambda: hub.last_received_code,
        ),
        HubStatusSensor(
            hub,
            key="last_learned_code",
            name="Last learned RF code",
            value_getter=lambda: hub.last_learned_code,
        ),
    ]
    for record in hub.store.records.values():
        entities.extend(_record_sensors(hub, record))
    async_add_entities(entities)

    @callback
    def add_sensors(record_id: str) -> None:
        if record_id in known_ids:
            return
        known_ids.add(record_id)
        async_add_entities(_record_sensors(hub, hub.store.records[record_id]))

    entry.async_on_unload(
        async_dispatcher_connect(hass, hub.signal_new_switch, add_sensors)
    )


def _record_sensors(
    hub: ESP32RFBridgeHub, record: SwitchRecord
) -> list[SensorEntity]:
    """Return learned-code sensors for one RF switch."""

    if record.protocol == PROTOCOL_HARJU:
        return []

    return [
        RecordCodesSensor(
            hub,
            record,
            key="incoming_on_codes",
            name="Incoming ON codes",
            value_getter=lambda: ", ".join(record.incoming_on_codes)
            or "No learned ON codes",
        ),
        RecordCodesSensor(
            hub,
            record,
            key="incoming_off_codes",
            name="Incoming OFF codes",
            value_getter=lambda: ", ".join(record.incoming_off_codes)
            or "No learned OFF codes",
        ),
    ]


class HubStatusSensor(SensorEntity):
    """A diagnostic status sensor for integration state."""

    _attr_has_entity_name = False

    def __init__(
        self,
        hub: ESP32RFBridgeHub,
        *,
        key: str,
        name: str,
        value_getter: Callable[[], str],
    ) -> None:
        """Initialize the sensor."""

        self.hub = hub
        self._value_getter = value_getter
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{hub.entry.entry_id}_{key}"
        self._attr_device_info = hub.device_info
        self._unsub_update: Callable[[], None] | None = None

    @property
    def native_value(self) -> str:
        """Return the current status value."""

        return self._value_getter()

    async def async_added_to_hass(self) -> None:
        """Register update listener."""

        @callback
        def _handle_update() -> None:
            self.async_write_ha_state()

        self._unsub_update = async_dispatcher_connect(
            self.hass, self.hub.signal_control_update, _handle_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister update listener."""

        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None


class RecordCodesSensor(SensorEntity):
    """A sensor showing learned incoming RF codes for one switch."""

    _attr_has_entity_name = False

    def __init__(
        self,
        hub: ESP32RFBridgeHub,
        record: SwitchRecord,
        *,
        key: str,
        name: str,
        value_getter: Callable[[], str],
    ) -> None:
        """Initialize the sensor."""

        self.hub = hub
        self.record = record
        self._value_getter = value_getter
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{record.id}_{key}"
        self._attr_device_info = hub.record_device_info(record)
        self._unsub_update: Callable[[], None] | None = None
        self._unsub_remove: Callable[[], None] | None = None

    @property
    def native_value(self) -> str:
        """Return learned codes."""

        return self._value_getter()

    async def async_added_to_hass(self) -> None:
        """Register update and remove listeners."""

        @callback
        def _handle_update(record_id: str) -> None:
            if record_id == self.record.id:
                self.async_write_ha_state()

        self._unsub_update = async_dispatcher_connect(
            self.hass, self.hub.signal_update, _handle_update
        )

        @callback
        def _handle_remove(record_id: str) -> None:
            if record_id == self.record.id:
                self.hass.async_create_task(self.async_remove(force_remove=True))

        self._unsub_remove = async_dispatcher_connect(
            self.hass, self.hub.signal_remove_switch, _handle_remove
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister listeners."""

        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None
        if self._unsub_remove:
            self._unsub_remove()
            self._unsub_remove = None
