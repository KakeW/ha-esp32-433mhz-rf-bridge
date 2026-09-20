"""Button platform for ESP32 433 MHz RF Bridge."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capabilities import capabilities_for
from .const import DOMAIN, LEARN_OFF, LEARN_ON, PROTOCOL_NEXA
from .hub import ESP32RFBridgeHub
from .store import SwitchRecord


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ESP32RFBridgeHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESP32 433 MHz RF Bridge button entities."""

    hub = entry.runtime_data
    known_ids = set(hub.store.records)
    entities: list[ButtonEntity] = [
        LearnAllOffButton(hub, PROTOCOL_NEXA, "Learn Nexa all off"),
        CreateSwitchButton(hub),
    ]
    for record in hub.store.records.values():
        entities.extend(_record_buttons(hub, record))
    async_add_entities(entities)

    @callback
    def add_buttons(record_id: str) -> None:
        if record_id in known_ids:
            return
        known_ids.add(record_id)
        async_add_entities(_record_buttons(hub, hub.store.records[record_id]))

    entry.async_on_unload(
        async_dispatcher_connect(hass, hub.signal_new_switch, add_buttons)
    )


def _record_buttons(
    hub: ESP32RFBridgeHub, record: SwitchRecord
) -> list[ButtonEntity]:
    """Return helper buttons for one RF switch."""

    buttons: list[ButtonEntity] = []
    capabilities = capabilities_for(record.protocol)
    if capabilities.learn_remote:
        buttons.extend(
            [
                RecordActionButton(
                    hub,
                    record,
                    key="learn_on",
                    label="Add incoming ON code",
                    action=lambda: hub.async_arm_learning(record.id, LEARN_ON),
                ),
                RecordActionButton(
                    hub,
                    record,
                    key="learn_off",
                    label="Add incoming OFF code",
                    action=lambda: hub.async_arm_learning(record.id, LEARN_OFF),
                ),
                RecordActionButton(
                    hub,
                    record,
                    key="clear_on",
                    label="Clear incoming ON codes",
                    action=lambda: hub.async_clear_learned_codes(
                        record.id, LEARN_ON
                    ),
                ),
                RecordActionButton(
                    hub,
                    record,
                    key="clear_off",
                    label="Clear incoming OFF codes",
                    action=lambda: hub.async_clear_learned_codes(
                        record.id, LEARN_OFF
                    ),
                ),
            ]
        )
    if capabilities.swap_transmit_polarity:
        buttons.append(
            RecordActionButton(
                hub,
                record,
                key="swap_transmit_codes",
                label="Swap transmitted ON/OFF codes",
                action=lambda: hub.async_swap_transmit_codes(record.id),
            )
        )
    buttons.append(
        RecordActionButton(
            hub,
            record,
            key="delete",
            label="Delete RF switch",
            action=lambda: hub.async_delete_record(record.id),
        )
    )
    return buttons


class BaseButton(ButtonEntity):
    """Base button tied to the integration device."""

    _attr_has_entity_name = False

    def __init__(self, hub: ESP32RFBridgeHub) -> None:
        """Initialize the button."""

        self.hub = hub
        self._attr_device_info = hub.device_info


class CreateSwitchButton(BaseButton):
    """Create a new RF switch with the next free virtual channel."""

    def __init__(self, hub: ESP32RFBridgeHub) -> None:
        """Initialize the button."""

        super().__init__(hub)
        self._attr_name = "Create new outlet"
        self._attr_unique_id = f"{DOMAIN}_{hub.entry.entry_id}_create_switch"

    async def async_press(self) -> None:
        """Handle the button press."""

        await self.hub.async_create_next_switch()


class LearnAllOffButton(BaseButton):
    """Learn an incoming RF code as an OFF command for one protocol."""

    def __init__(self, hub: ESP32RFBridgeHub, protocol: str, label: str) -> None:
        """Initialize the button."""

        super().__init__(hub)
        self.protocol = protocol
        self._attr_name = label
        self._attr_unique_id = (
            f"{DOMAIN}_{hub.entry.entry_id}_learn_{protocol}_all_off"
        )

    async def async_press(self) -> None:
        """Handle the button press."""

        await self.hub.async_arm_all_off_learning(self.protocol)


class RecordActionButton(BaseButton):
    """A helper action button for one RF switch."""

    def __init__(
        self,
        hub: ESP32RFBridgeHub,
        record: SwitchRecord,
        *,
        key: str,
        label: str,
        action: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize the button."""

        super().__init__(hub)
        self.record = record
        self._action = action
        self._attr_name = label
        self._attr_unique_id = f"{DOMAIN}_{record.id}_{key}"
        self._attr_device_info = hub.record_device_info(record)
        self._unsub_remove: Callable[[], None] | None = None

    async def async_press(self) -> None:
        """Handle the button press."""

        await self._action()

    async def async_added_to_hass(self) -> None:
        """Register remove listener."""

        @callback
        def _handle_remove(record_id: str) -> None:
            if record_id == self.record.id:
                self.hass.async_create_task(self.async_remove(force_remove=True))

        self._unsub_remove = async_dispatcher_connect(
            self.hass, self.hub.signal_remove_switch, _handle_remove
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister remove listener."""

        if self._unsub_remove:
            self._unsub_remove()
            self._unsub_remove = None
