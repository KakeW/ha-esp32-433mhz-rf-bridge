"""Switch platform for ESP32 433 MHz RF Bridge."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import ESP32RFBridgeHub
from .store import SwitchRecord


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ESP32RFBridgeHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESP32 433 MHz RF Bridge switch entities."""

    hub = entry.runtime_data
    known_ids = set(hub.store.records)

    @callback
    def add_switch(record_id: str) -> None:
        if record_id in known_ids:
            return
        known_ids.add(record_id)
        async_add_entities([ESP32RFBridgeSwitch(hub, hub.store.records[record_id])])

    async_add_entities(
        [ESP32RFBridgeSwitch(hub, record) for record in hub.store.records.values()]
    )
    entry.async_on_unload(
        async_dispatcher_connect(hass, hub.signal_new_switch, add_switch)
    )


class ESP32RFBridgeSwitch(SwitchEntity):
    """A switch controlled by pair-coded 433.92 MHz RF commands."""

    _attr_has_entity_name = False
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, hub: ESP32RFBridgeHub, record: SwitchRecord) -> None:
        """Initialize the switch."""

        self.hub = hub
        self.record = record
        self._attr_name = record.name
        self._attr_unique_id = f"{DOMAIN}_{record.id}"
        self._attr_device_info = hub.record_device_info(record)
        self._unsub_update: Callable[[], None] | None = None
        self._unsub_remove: Callable[[], None] | None = None

    @property
    def extra_state_attributes(self) -> dict:
        """Return current RF configuration details."""

        return {
            "switch_id": self.record.id,
            "channel": self.record.channel,
            "protocol": self.record.protocol,
            "send_service": self.record.send_service,
            "on_code": self.record.on_code,
            "off_code": self.record.off_code,
            "on_codes": self.record.on_codes,
            "off_codes": self.record.off_codes,
            "transmit_codes_swapped": self.record.transmit_codes_swapped,
        }

    @property
    def icon(self) -> str:
        """Return a toggle-style icon instead of the generic switch icon."""

        return "mdi:toggle-switch" if self.is_on else "mdi:toggle-switch-off-outline"

    async def async_added_to_hass(self) -> None:
        """Register update listener."""

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
        """Unregister update listener."""

        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None
        if self._unsub_remove:
            self._unsub_remove()
            self._unsub_remove = None

    @property
    def is_on(self) -> bool | None:
        """Return the inferred switch state."""

        return self.record.state

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""

        await self.hub.async_turn_record(self.record, True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""

        await self.hub.async_turn_record(self.record, False)
