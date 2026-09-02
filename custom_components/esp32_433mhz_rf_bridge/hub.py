"""Runtime hub for RF switch state and service calls."""

from __future__ import annotations

from collections.abc import Callable
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_CODE,
    ATTR_KIND,
    ATTR_PROTOCOL,
    CONF_FIRST_CHANNEL,
    CONF_RECEIVE_ENTITY,
    CONF_SEND_SERVICE,
    CONF_TRANSMITTER_ID,
    DEFAULT_HARJU_SEND_SERVICE,
    DEFAULT_FIRST_CHANNEL,
    DEFAULT_RECEIVE_ENTITY,
    DEFAULT_SEND_SERVICE,
    DEFAULT_SWITCH_PROTOCOL,
    DEFAULT_TRANSMITTER_ID,
    DOMAIN,
    EVENT_RF_RECEIVED,
    LEARN_OFF,
    LEARN_ON,
    PROTOCOL_HARJU,
    PROTOCOL_NEXA,
)
from .protocol import (
    HarjuCodeFamily,
    ProtocolError,
    classify_harju_code,
    expand_harju_code,
    nexa_transmitter_id,
    generate_code_pair,
    generate_harju_code_pair,
    normalize_rf_code,
)
from .store import RFStore, SwitchRecord

LOGGER = logging.getLogger(__name__)
RF_CODE_SEARCH_RE = re.compile(r"(?<![0-9A-Fa-f])(?:[01]{24}|[0-9A-Fa-f]{16})(?![0-9A-Fa-f])")
ALL_SWITCHES_LEARN_TARGET = "__all_switches__"
LEARN_CAPTURE_SECONDS = 8.0


class ESP32RFBridgeHub:
    """Coordinate RF codes, state and Home Assistant service calls."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the hub."""

        self.hass = hass
        self.entry = entry
        self.store = RFStore(hass)
        self._unsubscribers: list[Callable[[], None]] = []
        self._learn_target: tuple[str, str, str | None] | None = None
        self._learn_captured_codes: set[str] = set()
        self._learn_finish_unsub: Callable[[], None] | None = None
        self.device_entry_id: str | None = None
        self.new_switch_name = ""
        self.new_switch_protocol = DEFAULT_SWITCH_PROTOCOL
        self.learning_status = "Not learning"
        self.last_learned_code = "No learned codes"
        self.last_received_code = "No received codes"
        self.last_receive_source = "No reception"

    @property
    def signal_new_switch(self) -> str:
        """Dispatcher signal for adding newly created switch entities."""

        return f"{DOMAIN}_{self.entry.entry_id}_new_switch"

    @property
    def signal_update(self) -> str:
        """Dispatcher signal for state updates."""

        return f"{DOMAIN}_{self.entry.entry_id}_update"

    @property
    def signal_remove_switch(self) -> str:
        """Dispatcher signal for removing switch-related entities."""

        return f"{DOMAIN}_{self.entry.entry_id}_remove_switch"

    @property
    def signal_control_update(self) -> str:
        """Dispatcher signal for shared control/status entity updates."""

        return f"{DOMAIN}_{self.entry.entry_id}_control_update"

    @property
    def device_info(self) -> dict:
        """Return common device info for integration entities."""

        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": "ESP32 433 MHz RF Bridge",
            "manufacturer": "Local",
        }

    def record_device_info(self, record: SwitchRecord) -> dict:
        """Return device info for one logical RF switch."""

        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, record.id)},
            "name": record.name,
            "manufacturer": "Local",
        }
        if self.device_entry_id is not None:
            info["via_device_id"] = self.device_entry_id
        return info

    async def async_setup(self) -> None:
        """Load storage and start event listeners."""

        await self.store.async_load()
        bridge_device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="ESP32 433 MHz RF Bridge",
            manufacturer="Local",
        )
        self.device_entry_id = bridge_device.id
        await self._repair_harju_generated_polarity()
        await self._repair_duplicate_harju_codes()
        await self._migrate_harju_code_families()
        await self._cleanup_invalid_learned_codes()
        self._cleanup_deprecated_test_buttons()
        self._cleanup_record_delete_buttons()
        self._cleanup_deprecated_receive_select()
        self._cleanup_deprecated_status_sensors()
        self._cleanup_orphaned_switch_registry_entries()
        self._unsubscribers.append(
            self.hass.bus.async_listen(EVENT_RF_RECEIVED, self._async_event_received)
        )
        self._unsubscribers.append(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)
        )

    async def async_unload(self) -> None:
        """Unload event listeners."""

        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self._cancel_learning_timer()

    def generate_pair_for_next_channel(self) -> tuple[int, str, str]:
        """Generate an RF code pair for the next available channel."""

        first_channel = self._entry_value(CONF_FIRST_CHANNEL, DEFAULT_FIRST_CHANNEL)
        channel = self.store.next_channel(int(first_channel))
        transmitter_id = self._entry_value(CONF_TRANSMITTER_ID, DEFAULT_TRANSMITTER_ID)
        pair = generate_code_pair(channel, str(transmitter_id))
        return channel, pair.on_code, pair.off_code

    def next_switch_default_name(self) -> str:
        """Return the default name for the next switch."""

        if self.new_switch_protocol == PROTOCOL_HARJU:
            first_channel = self._entry_value(CONF_FIRST_CHANNEL, DEFAULT_FIRST_CHANNEL)
            channel = self.store.next_channel(int(first_channel))
            return f"Harju {channel}"
        first_channel = self._entry_value(CONF_FIRST_CHANNEL, DEFAULT_FIRST_CHANNEL)
        channel = self.store.next_channel(int(first_channel))
        return f"RF switch {channel}"

    def set_new_switch_name(self, name: str) -> None:
        """Set the pending switch name from the GUI text entity."""

        self.new_switch_name = name.strip()
        async_dispatcher_send(self.hass, self.signal_control_update)

    def set_new_switch_protocol(self, protocol: str) -> None:
        """Set the protocol used for the next created RF switch."""

        if protocol not in {PROTOCOL_NEXA, PROTOCOL_HARJU}:
            raise HomeAssistantError("Unknown RF protocol")
        self.new_switch_protocol = protocol
        self.new_switch_name = self.next_switch_default_name()
        async_dispatcher_send(self.hass, self.signal_control_update)

    async def async_set_receive_entity(self, entity_id: str) -> None:
        """Store the selected RF receive text sensor entity."""

        options = dict(self.entry.options)
        options[CONF_RECEIVE_ENTITY] = entity_id
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        async_dispatcher_send(self.hass, self.signal_control_update)

    async def async_create_switch(
        self,
        name: str,
        *,
        channel: int | None = None,
        on_code: str | None = None,
        off_code: str | None = None,
        protocol: str = PROTOCOL_NEXA,
        send_service: str | None = None,
    ) -> SwitchRecord:
        """Create and persist a new RF switch."""

        if protocol not in {PROTOCOL_NEXA, PROTOCOL_HARJU}:
            raise HomeAssistantError("Unknown RF protocol")

        if on_code is not None and off_code is not None:
            if channel is None:
                channel = self.store.next_channel(
                    int(self._entry_value(CONF_FIRST_CHANNEL, DEFAULT_FIRST_CHANNEL))
                )
            normalized_on = normalize_rf_code(on_code)
            normalized_off = normalize_rf_code(off_code)
        elif on_code is None and off_code is None:
            if protocol == PROTOCOL_HARJU:
                if channel is None:
                    channel = self.store.next_channel(
                        int(
                            self._entry_value(
                                CONF_FIRST_CHANNEL, DEFAULT_FIRST_CHANNEL
                            )
                        )
                    )
                pair = generate_harju_code_pair(channel)
                channel = pair.channel
                normalized_on = pair.on_code
                normalized_off = pair.off_code
            elif channel is None:
                channel, normalized_on, normalized_off = (
                    self.generate_pair_for_next_channel()
                )
            else:
                transmitter_id = self._entry_value(
                    CONF_TRANSMITTER_ID, DEFAULT_TRANSMITTER_ID
                )
                pair = generate_code_pair(channel, str(transmitter_id))
                normalized_on = pair.on_code
                normalized_off = pair.off_code
        else:
            raise HomeAssistantError("Both on_code and off_code must be provided")

        selected_send_service = send_service
        if selected_send_service is None:
            selected_send_service = (
                DEFAULT_HARJU_SEND_SERVICE
                if protocol == PROTOCOL_HARJU
                else str(self._entry_value(CONF_SEND_SERVICE, DEFAULT_SEND_SERVICE))
            )

        record = self.store.add_record(
            name=name,
            channel=int(channel),
            on_code=normalized_on,
            off_code=normalized_off,
            protocol=protocol,
            send_service=selected_send_service,
            on_codes=self._initial_command_codes(protocol, normalized_on),
            off_codes=self._initial_command_codes(protocol, normalized_off),
        )
        await self.store.async_save()
        async_dispatcher_send(self.hass, self.signal_new_switch, record.id)
        return record

    async def async_delete_record(self, record_id: str) -> None:
        """Delete a switch and remove its entities."""

        record = self.store.remove_record(record_id)
        if record is None:
            raise HomeAssistantError("Unknown RF switch")

        if self._learn_target and self._learn_target[0] == record_id:
            self._learn_target = None
            self._learn_captured_codes.clear()
            self._cancel_learning_timer()
            self.learning_status = "Not learning"
            async_dispatcher_send(self.hass, self.signal_control_update)

        await self.store.async_save()
        async_dispatcher_send(self.hass, self.signal_remove_switch, record_id)
        self._remove_switch_registry_entries(record_id)
        async_dispatcher_send(self.hass, self.signal_control_update)

    async def async_clear_learned_codes(self, record_id: str, kind: str) -> None:
        """Clear learned incoming RF codes for one switch direction."""

        record = self.store.records.get(record_id)
        if record is None:
            raise HomeAssistantError("Unknown RF switch")
        if kind == LEARN_ON:
            record.incoming_on_codes.clear()
        elif kind == LEARN_OFF:
            record.incoming_off_codes.clear()
        else:
            raise HomeAssistantError("kind must be 'on' or 'off'")

        await self.store.async_save()
        async_dispatcher_send(self.hass, self.signal_update, record_id)

    async def async_create_next_switch(self) -> SwitchRecord:
        """Create a switch with the next virtual channel and GUI-provided name."""

        channel, on_code, off_code = self.generate_pair_for_next_channel()
        protocol = self.new_switch_protocol
        if protocol == PROTOCOL_HARJU:
            first_channel = self._entry_value(CONF_FIRST_CHANNEL, DEFAULT_FIRST_CHANNEL)
            channel = self.store.next_channel(int(first_channel))
            pair = generate_harju_code_pair(channel)
            channel, on_code, off_code = pair.channel, pair.on_code, pair.off_code
        record = await self.async_create_switch(
            self.new_switch_name or self.next_switch_default_name(),
            channel=channel,
            on_code=on_code,
            off_code=off_code,
            protocol=protocol,
        )
        self.new_switch_name = self.next_switch_default_name()
        async_dispatcher_send(self.hass, self.signal_control_update)
        return record

    async def async_send_code(
        self, code: str, send_service: str | None = None
    ) -> None:
        """Send an RF code through the configured ESPHome action."""

        normalized = normalize_rf_code(code)
        service_ref = send_service or self._entry_value(CONF_SEND_SERVICE, DEFAULT_SEND_SERVICE)
        try:
            domain, service = str(service_ref).split(".", 1)
        except ValueError as err:
            raise HomeAssistantError(
                "send_service must use the format domain.service"
            ) from err

        await self.hass.services.async_call(
            domain,
            service,
            {ATTR_CODE: normalized},
            blocking=True,
        )

    async def async_turn_record(self, record: SwitchRecord, is_on: bool) -> None:
        """Transmit a switch command and update inferred state."""

        primary_code = record.on_code if is_on else record.off_code
        codes = record.on_codes if is_on else record.off_codes
        send_codes = (
            list(dict.fromkeys(codes or [primary_code]))
            if record.protocol == PROTOCOL_HARJU
            else [primary_code]
        )
        for code in send_codes:
            await self.async_send_code(code, record.send_service)
        await self.async_set_record_state(record, is_on)

    async def async_set_record_state(
        self, record: SwitchRecord, is_on: bool | None
    ) -> None:
        """Set inferred state for a switch record."""

        if record.state == is_on:
            return
        record.state = is_on
        await self.store.async_save()
        async_dispatcher_send(self.hass, self.signal_update, record.id)

    async def async_arm_learning(self, record_id: str, kind: str) -> None:
        """Capture the next received RF code for a switch."""

        if record_id not in self.store.records:
            raise HomeAssistantError("Unknown RF switch")
        if kind not in {LEARN_ON, LEARN_OFF}:
            raise HomeAssistantError("kind must be 'on' or 'off'")
        self._cancel_learning_timer()
        self._learn_target = (record_id, kind, None)
        self._learn_captured_codes.clear()
        record = self.store.records[record_id]
        self.learning_status = (
            f"Waiting for {record.name} "
            f"{'ON' if kind == LEARN_ON else 'OFF'} code"
        )
        async_dispatcher_send(self.hass, self.signal_control_update)

    async def async_arm_all_off_learning(self, protocol: str) -> None:
        """Capture the next received RF code as an OFF code for one protocol."""

        if protocol not in {PROTOCOL_NEXA, PROTOCOL_HARJU}:
            raise HomeAssistantError("Unknown RF protocol")
        if not any(record.protocol == protocol for record in self.store.records.values()):
            raise HomeAssistantError(f"No {protocol} RF switches have been created")
        self._cancel_learning_timer()
        self._learn_target = (ALL_SWITCHES_LEARN_TARGET, LEARN_OFF, protocol)
        self._learn_captured_codes.clear()
        label = "Harju" if protocol == PROTOCOL_HARJU else "Nexa"
        self.learning_status = f"Waiting for {label} all-off code"
        async_dispatcher_send(self.hass, self.signal_control_update)

    async def async_receive_code(self, code: str) -> None:
        """Process an incoming RF code from ESPHome or an HA automation."""

        normalized = normalize_rf_code(code)
        self.last_received_code = normalized
        async_dispatcher_send(self.hass, self.signal_control_update)

        if self._learn_target is not None:
            record_id, kind, protocol = self._learn_target
            stored = await self._async_store_learned_code(
                record_id, kind, normalized, protocol
            )
            self._schedule_learning_finish()
            count = len(self._learn_captured_codes)
            if stored:
                self.learning_status = (
                    f"Code captured, waiting for more variants ({count})"
                )
                self.last_learned_code = self._learned_status_text(
                    record_id, kind, protocol
                )
                if self._learning_complete_after_code(
                    record_id, kind, protocol, normalized
                ):
                    await self._async_finish_learning()
                    return
            else:
                self.learning_status = "Ignored code from another protocol"
            async_dispatcher_send(self.hass, self.signal_control_update)
            return

        changed = False
        for record in self.store.records.values():
            if not self._record_accepts_received_code(record, normalized):
                continue
            if normalized in {
                record.on_code,
                *record.on_codes,
                *record.incoming_on_codes,
            }:
                record.state = True
                changed = True
                async_dispatcher_send(self.hass, self.signal_update, record.id)
            elif normalized in {
                record.off_code,
                *record.off_codes,
                *record.incoming_off_codes,
            }:
                record.state = False
                changed = True
                async_dispatcher_send(self.hass, self.signal_update, record.id)

        if changed:
            await self.store.async_save()

    async def _async_store_learned_code(
        self, record_id: str, kind: str, code: str, protocol: str | None
    ) -> bool:
        """Store one learned RF code without ending the capture window."""

        if code in self._learn_captured_codes:
            return True

        if record_id == ALL_SWITCHES_LEARN_TARGET:
            family = classify_harju_code(code) if protocol == PROTOCOL_HARJU else None
            if family is not None and family.command != LEARN_OFF:
                return False
            learned_codes = family.codes if family is not None else (code,)
            changed_record_ids: list[str] = []
            eligible_records = 0
            for record in self.store.records.values():
                if protocol is not None and record.protocol != protocol:
                    continue
                if not self._record_accepts_received_code(record, code):
                    continue
                eligible_records += 1
                changed = False
                for learned_code in learned_codes:
                    if (
                        record.protocol == PROTOCOL_NEXA
                        and learned_code in record.incoming_on_codes
                    ):
                        record.incoming_on_codes.remove(learned_code)
                        changed = True
                    if learned_code not in record.incoming_off_codes:
                        record.incoming_off_codes.append(learned_code)
                        changed = True
                if changed:
                    changed_record_ids.append(record.id)
            if eligible_records == 0:
                return False
            self._learn_captured_codes.update(learned_codes)
            await self.store.async_save()
            for changed_record_id in changed_record_ids:
                async_dispatcher_send(
                    self.hass, self.signal_update, changed_record_id
                )
            return True

        record = self.store.records[record_id]
        if not self._record_accepts_received_code(record, code):
            return False
        family = (
            classify_harju_code(code)
            if record.protocol == PROTOCOL_HARJU
            else None
        )
        if family is not None and family.command != kind:
            return False
        learned_codes = family.codes if family is not None else (code,)
        target_list = (
            record.incoming_on_codes if kind == LEARN_ON else record.incoming_off_codes
        )
        opposite_list = (
            record.incoming_off_codes
            if kind == LEARN_ON
            else record.incoming_on_codes
        )
        for learned_code in learned_codes:
            if record.protocol == PROTOCOL_NEXA and learned_code in opposite_list:
                opposite_list.remove(learned_code)
            if learned_code not in target_list:
                target_list.append(learned_code)
        self._learn_captured_codes.update(learned_codes)
        if family is not None and not family.is_all:
            self._adopt_harju_command_family(record, kind, family)
        await self.store.async_save()
        async_dispatcher_send(self.hass, self.signal_update, record.id)
        return True

    def _learned_status_text(
        self, record_id: str, kind: str, protocol: str | None
    ) -> str:
        """Return a compact status text for the current learned burst."""

        codes = ", ".join(sorted(self._learn_captured_codes))
        if record_id == ALL_SWITCHES_LEARN_TARGET:
            label = "Harju" if protocol == PROTOCOL_HARJU else "Nexa"
            return f"{label} all off: {codes}"

        record = self.store.records[record_id]
        direction = "ON" if kind == LEARN_ON else "OFF"
        return f"{record.name} {direction}: {codes}"

    def _schedule_learning_finish(self) -> None:
        """Finish the active learning window after RF burst reception quiets down."""

        self._cancel_learning_timer()

        @callback
        def _finish(_now) -> None:
            self.hass.async_create_task(self._async_finish_learning())

        self._learn_finish_unsub = async_call_later(
            self.hass, LEARN_CAPTURE_SECONDS, _finish
        )

    async def _async_finish_learning(self) -> None:
        """Finish the current learning window."""

        target = self._learn_target
        count = len(self._learn_captured_codes)
        self._learn_target = None
        self._learn_captured_codes.clear()
        self._cancel_learning_timer()

        if target is None:
            self.learning_status = "Not learning"
        elif count == 0:
            self.learning_status = "No code captured"
        elif target[0] == ALL_SWITCHES_LEARN_TARGET:
            label = "Harju" if target[2] == PROTOCOL_HARJU else "Nexa"
            self.learning_status = f"{label} all-off codes captured ({count})"
        else:
            self.learning_status = f"Codes captured ({count})"

        async_dispatcher_send(self.hass, self.signal_control_update)

    def _cancel_learning_timer(self) -> None:
        """Cancel the pending learning-window timer."""

        if self._learn_finish_unsub is not None:
            self._learn_finish_unsub()
            self._learn_finish_unsub = None

    def _record_accepts_received_code(self, record: SwitchRecord, code: str) -> bool:
        """Return whether a received code belongs to a switch protocol namespace."""

        if record.protocol == PROTOCOL_HARJU:
            return len(code) == 24 and set(code) <= {"0", "1"}

        if record.protocol == PROTOCOL_NEXA:
            if len(code) != 16:
                return False
            try:
                nexa_transmitter_id(code)
            except ProtocolError:
                return False
            return True

        return False

    @staticmethod
    def _initial_command_codes(protocol: str, code: str) -> list[str]:
        """Return a known Harju family or the single backwards-compatible code."""

        if protocol == PROTOCOL_HARJU:
            family_codes = expand_harju_code(code)
            if family_codes is not None:
                return list(family_codes)
        return [code]

    def _learning_complete_after_code(
        self, record_id: str, kind: str, protocol: str | None, code: str
    ) -> bool:
        """Return whether one received code completed the active learning."""

        selected_protocol = protocol
        if record_id != ALL_SWITCHES_LEARN_TARGET:
            selected_protocol = self.store.records[record_id].protocol
        if selected_protocol == PROTOCOL_NEXA:
            return True
        family = classify_harju_code(code) if selected_protocol == PROTOCOL_HARJU else None
        return family is not None and family.command == kind

    @staticmethod
    def _adopt_harju_command_family(
        record: SwitchRecord, kind: str, family: HarjuCodeFamily
    ) -> None:
        """Use a known family for Harju TX unless another family is already selected."""

        current_codes = record.on_codes if kind == LEARN_ON else record.off_codes
        selected_families = {
            known.key
            for code in current_codes
            if (known := classify_harju_code(code)) is not None and not known.is_all
        }
        if selected_families and family.key not in selected_families:
            return
        if kind == LEARN_ON:
            record.on_codes = list(family.codes)
        else:
            record.off_codes = list(family.codes)

    async def _migrate_harju_code_families(self) -> None:
        """Expand known legacy Harju command and alias codes without data loss."""

        changed = False
        for record in self.store.records.values():
            if record.protocol != PROTOCOL_HARJU:
                continue

            for kind in (LEARN_ON, LEARN_OFF):
                command_codes = record.on_codes if kind == LEARN_ON else record.off_codes
                incoming_codes = (
                    record.incoming_on_codes
                    if kind == LEARN_ON
                    else record.incoming_off_codes
                )
                expanded_incoming = self._expand_known_harju_aliases(
                    incoming_codes, kind
                )
                if expanded_incoming != incoming_codes:
                    if kind == LEARN_ON:
                        record.incoming_on_codes = expanded_incoming
                    else:
                        record.incoming_off_codes = expanded_incoming
                    changed = True

                family = self._single_harju_command_family(command_codes, kind)
                if family is None:
                    family = self._single_harju_command_family(
                        expanded_incoming, kind
                    )
                if family is not None and list(family.codes) != command_codes:
                    self._adopt_harju_command_family(record, kind, family)
                    changed = True

        if changed:
            await self.store.async_save()

    @staticmethod
    def _expand_known_harju_aliases(codes: list[str], kind: str) -> list[str]:
        """Expand every matching known alias family while preserving unknown codes."""

        expanded: list[str] = []
        for code in codes:
            family = classify_harju_code(code)
            additions = (
                family.codes
                if family is not None and family.command == kind
                else (code,)
            )
            for addition in additions:
                if addition not in expanded:
                    expanded.append(addition)
        return expanded

    @staticmethod
    def _single_harju_command_family(
        codes: list[str], kind: str
    ) -> HarjuCodeFamily | None:
        """Return one unambiguous non-ALL family represented by the codes."""

        families = {
            family.key: family
            for code in codes
            if (family := classify_harju_code(code)) is not None
            and family.command == kind
            and not family.is_all
        }
        return next(iter(families.values())) if len(families) == 1 else None

    async def _cleanup_invalid_learned_codes(self) -> None:
        """Remove learned codes that cannot belong to their switch protocol."""

        changed = False
        for record in self.store.records.values():
            incoming_on_codes = [
                code
                for code in record.incoming_on_codes
                if self._record_accepts_received_code(record, code)
            ]
            incoming_off_codes = [
                code
                for code in record.incoming_off_codes
                if self._record_accepts_received_code(record, code)
            ]
            if incoming_on_codes != record.incoming_on_codes:
                record.incoming_on_codes = incoming_on_codes
                changed = True
            if incoming_off_codes != record.incoming_off_codes:
                record.incoming_off_codes = incoming_off_codes
                changed = True

        if changed:
            await self.store.async_save()

    @callback
    def _async_event_received(self, event: Event) -> None:
        """Handle an RF received event."""

        code = event.data.get(ATTR_CODE)
        if not code:
            return
        self.last_receive_source = EVENT_RF_RECEIVED
        self.hass.async_create_task(self.async_receive_code(str(code)))

    @callback
    def _async_state_changed(self, event: Event) -> None:
        """Handle an RF code published by the configured ESPHome text sensor."""

        receive_entity = self._entry_value(
            CONF_RECEIVE_ENTITY, DEFAULT_RECEIVE_ENTITY
        )
        entity_id = event.data.get("entity_id")
        new_state: State | None = event.data.get("new_state")
        if new_state is None or not self._is_receive_state(
            str(entity_id), new_state, str(receive_entity)
        ):
            return

        if new_state is None or new_state.state in {
            "",
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        }:
            return

        self.hass.async_create_task(
            self._async_receive_state_code(new_state.state, str(entity_id))
        )

    async def _async_receive_state_code(self, code: str, entity_id: str) -> None:
        """Process a text sensor state as an RF code without breaking HA events."""

        match = RF_CODE_SEARCH_RE.search(code)
        if match is None:
            LOGGER.debug(
                "Ignoring value without RF code from configured receive entity %s: %s",
                entity_id,
                code,
            )
            return

        try:
            self.last_receive_source = entity_id
            await self.async_receive_code(match.group(0))
        except ProtocolError as err:
            LOGGER.debug(
                "Ignoring non-RF value from configured receive entity %s: %s",
                entity_id,
                err,
            )

    def _is_receive_state(
        self, entity_id: str, new_state: State, configured_entity_id: str
    ) -> bool:
        """Return whether a state change looks like an ESPHome RF code source."""

        if new_state.state in {"", STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return False

        if entity_id == configured_entity_id:
            return True

        if not entity_id.startswith("text_sensor."):
            return False

        if RF_CODE_SEARCH_RE.search(new_state.state) is None:
            return False

        friendly_name = str(new_state.attributes.get("friendly_name", ""))
        haystack = f"{entity_id} {friendly_name}".lower()
        return (
            "rf" in haystack
            or "radio" in haystack
            or "viimeisin" in haystack
            or "debug" in haystack
        )

    def _entry_value(self, key: str, default: Any) -> Any:
        """Read an option override, falling back to initial config data."""

        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def receive_entity(self) -> str:
        """Return the configured ESPHome receive text sensor entity ID."""

        return str(self._entry_value(CONF_RECEIVE_ENTITY, DEFAULT_RECEIVE_ENTITY))

    def _cleanup_deprecated_test_buttons(self) -> None:
        """Remove button entities that older versions created for duplicate tests."""

        registry = er.async_get(self.hass)
        deprecated_unique_ids = {
            f"{DOMAIN}_{self.entry.entry_id}_process_receive_entity",
            f"{DOMAIN}_{self.entry.entry_id}_learn_all_off",
        }
        for entity_entry in er.async_entries_for_config_entry(
            registry, self.entry.entry_id
        ):
            if entity_entry.domain != "button" or not entity_entry.unique_id:
                continue
            if (
                entity_entry.unique_id in deprecated_unique_ids
                or entity_entry.unique_id.endswith(("_test_on", "_test_off"))
            ):
                registry.async_remove(entity_entry.entity_id)

    def _cleanup_record_delete_buttons(self) -> None:
        """Recreate delete buttons so they are added after other record buttons."""

        registry = er.async_get(self.hass)
        for entity_entry in er.async_entries_for_config_entry(
            registry, self.entry.entry_id
        ):
            if (
                entity_entry.domain == "button"
                and entity_entry.unique_id
                and entity_entry.unique_id.endswith("_delete")
            ):
                registry.async_remove(entity_entry.entity_id)

    def _cleanup_deprecated_receive_select(self) -> None:
        """Remove the old receive-source select entity."""

        registry = er.async_get(self.hass)
        unique_id = f"{DOMAIN}_{self.entry.entry_id}_receive_entity_select"
        for entity_entry in er.async_entries_for_config_entry(
            registry, self.entry.entry_id
        ):
            if entity_entry.unique_id == unique_id:
                registry.async_remove(entity_entry.entity_id)

    def _cleanup_deprecated_status_sensors(self) -> None:
        """Remove diagnostic sensors that are now only shown in options/logs."""

        registry = er.async_get(self.hass)
        deprecated_unique_ids = {
            f"{DOMAIN}_{self.entry.entry_id}_last_receive_source",
            f"{DOMAIN}_{self.entry.entry_id}_receive_entity",
        }
        for entity_entry in er.async_entries_for_config_entry(
            registry, self.entry.entry_id
        ):
            if entity_entry.unique_id in deprecated_unique_ids:
                registry.async_remove(entity_entry.entity_id)

    def _cleanup_orphaned_switch_registry_entries(self) -> None:
        """Remove switch devices left behind by older delete behavior."""

        entity_registry = er.async_get(self.hass)
        known_record_ids = set(self.store.records)
        orphan_record_ids: set[str] = set()

        for entity_entry in er.async_entries_for_config_entry(
            entity_registry, self.entry.entry_id
        ):
            record_id = self._record_id_from_unique_id(entity_entry.unique_id)
            if record_id is not None and record_id not in known_record_ids:
                orphan_record_ids.add(record_id)

        device_registry = dr.async_get(self.hass)
        for device_entry in dr.async_entries_for_config_entry(
            device_registry, self.entry.entry_id
        ):
            for identifier_domain, identifier_id in device_entry.identifiers:
                if (
                    identifier_domain == DOMAIN
                    and identifier_id != self.entry.entry_id
                    and identifier_id not in known_record_ids
                ):
                    orphan_record_ids.add(identifier_id)

        for record_id in orphan_record_ids:
            self._remove_switch_registry_entries(record_id)

    def _remove_switch_registry_entries(self, record_id: str) -> None:
        """Remove all HA registry entries belonging to one logical switch."""

        entity_registry = er.async_get(self.hass)
        for entity_entry in er.async_entries_for_config_entry(
            entity_registry, self.entry.entry_id
        ):
            if self._record_id_from_unique_id(entity_entry.unique_id) == record_id:
                entity_registry.async_remove(entity_entry.entity_id)

        device_registry = dr.async_get(self.hass)
        device_entry = self._get_switch_device_entry(device_registry, record_id)
        if device_entry is not None:
            device_registry.async_remove_device(device_entry.id)

    def _get_switch_device_entry(
        self, device_registry: dr.DeviceRegistry, record_id: str
    ) -> dr.DeviceEntry | None:
        """Return the HA device registry entry for one switch."""

        identifier = (DOMAIN, record_id)
        if hasattr(device_registry, "async_get_device_by_identifier"):
            return device_registry.async_get_device_by_identifier(
                identifier, self.entry.entry_id
            )
        return device_registry.async_get_device(identifiers={identifier})

    def _record_id_from_unique_id(self, unique_id: str | None) -> str | None:
        """Return the switch record id for entity unique IDs tied to records."""

        if not unique_id or not unique_id.startswith(f"{DOMAIN}_"):
            return None

        raw_id = unique_id.removeprefix(f"{DOMAIN}_")
        for record_id in self.store.records:
            if raw_id == record_id or raw_id.startswith(f"{record_id}_"):
                return record_id

        if raw_id == self.entry.entry_id or raw_id.startswith(f"{self.entry.entry_id}_"):
            return None

        return raw_id.split("_", 1)[0]

    async def _repair_duplicate_harju_codes(self) -> None:
        """Give duplicate Harju records unique generated send codes."""

        seen_pairs: set[tuple[str, str]] = set()
        changed = False
        first_channel = int(
            self._entry_value(CONF_FIRST_CHANNEL, DEFAULT_FIRST_CHANNEL)
        )

        for record in self.store.records.values():
            if record.protocol != PROTOCOL_HARJU:
                continue
            pair_key = (record.on_code, record.off_code)
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                continue

            channel = self.store.next_channel(first_channel)
            while True:
                pair = generate_harju_code_pair(channel)
                candidate_key = (pair.on_code, pair.off_code)
                if candidate_key not in seen_pairs:
                    break
                channel += 1

            record.channel = pair.channel
            record.on_code = pair.on_code
            record.off_code = pair.off_code
            record.on_codes = self._initial_command_codes(PROTOCOL_HARJU, pair.on_code)
            record.off_codes = self._initial_command_codes(PROTOCOL_HARJU, pair.off_code)
            seen_pairs.add(candidate_key)
            changed = True

        if changed:
            await self.store.async_save()

    async def _repair_harju_generated_polarity(self) -> None:
        """Swap old generated Harju ON/OFF pairs that were stored inverted."""

        changed = False
        for record in self.store.records.values():
            if record.protocol != PROTOCOL_HARJU or record.channel == 2:
                continue

            expected_pair = generate_harju_code_pair(record.channel)
            if (
                record.on_code == expected_pair.off_code
                and record.off_code == expected_pair.on_code
            ):
                record.on_code = expected_pair.on_code
                record.off_code = expected_pair.off_code
                record.on_codes = self._initial_command_codes(
                    PROTOCOL_HARJU, expected_pair.on_code
                )
                record.off_codes = self._initial_command_codes(
                    PROTOCOL_HARJU, expected_pair.off_code
                )
                changed = True

        if changed:
            await self.store.async_save()


def protocol_error_to_ha_error(err: ProtocolError) -> HomeAssistantError:
    """Convert protocol errors to user-facing Home Assistant errors."""

    return HomeAssistantError(str(err))
