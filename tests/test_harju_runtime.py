"""Lightweight runtime tests for Harju family handling in the integration hub."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types


ROOT = Path(__file__).parents[1]
PACKAGE = "custom_components.esp32_433mhz_rf_bridge"


def _install_homeassistant_stubs() -> None:
    """Install only the Home Assistant symbols needed to import the hub."""

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    const = types.ModuleType("homeassistant.const")
    core = types.ModuleType("homeassistant.core")
    exceptions = types.ModuleType("homeassistant.exceptions")
    helpers = types.ModuleType("homeassistant.helpers")
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    event = types.ModuleType("homeassistant.helpers.event")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    storage = types.ModuleType("homeassistant.helpers.storage")

    class ConfigEntry:
        pass

    class Event:
        pass

    class HomeAssistant:
        pass

    class State:
        pass

    class HomeAssistantError(Exception):
        pass

    class Store:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *_args, **_kwargs):
            pass

    config_entries.ConfigEntry = ConfigEntry
    const.EVENT_STATE_CHANGED = "state_changed"
    const.STATE_UNAVAILABLE = "unavailable"
    const.STATE_UNKNOWN = "unknown"
    core.Event = Event
    core.HomeAssistant = HomeAssistant
    core.State = State
    core.callback = lambda function: function
    exceptions.HomeAssistantError = HomeAssistantError
    dispatcher.async_dispatcher_send = lambda *_args, **_kwargs: None
    event.async_call_later = lambda *_args, **_kwargs: (lambda: None)
    device_registry.DeviceRegistry = object
    device_registry.DeviceEntry = object
    device_registry.async_get = lambda _hass: None
    device_registry.async_entries_for_config_entry = lambda *_args: []
    entity_registry.async_get = lambda _hass: None
    entity_registry.async_entries_for_config_entry = lambda *_args: []
    storage.Store = Store
    helpers.device_registry = device_registry
    helpers.entity_registry = entity_registry

    modules = {
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
        "homeassistant.const": const,
        "homeassistant.core": core,
        "homeassistant.exceptions": exceptions,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.dispatcher": dispatcher,
        "homeassistant.helpers.event": event,
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.helpers.storage": storage,
    }
    sys.modules.update(modules)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_integration_modules():
    if "homeassistant" not in sys.modules:
        _install_homeassistant_stubs()

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT / "custom_components" / "esp32_433mhz_rf_bridge")]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault(PACKAGE, package)

    component = ROOT / "custom_components" / "esp32_433mhz_rf_bridge"
    const = _load_module(f"{PACKAGE}.const", component / "const.py")
    protocol = _load_module(f"{PACKAGE}.protocol", component / "protocol.py")
    store = _load_module(f"{PACKAGE}.store", component / "store.py")
    hub = _load_module(f"{PACKAGE}.hub", component / "hub.py")
    return const, protocol, store, hub


const, protocol, store, hub_module = _load_integration_modules()


class FakeStore:
    """Minimal persistence wrapper used by the hub behavior tests."""

    def __init__(self, records):
        self.records = {record.id: record for record in records}
        self.save_count = 0

    async def async_save(self) -> None:
        self.save_count += 1


def make_record(
    *,
    protocol_name: str,
    on_code: str,
    off_code: str,
    on_codes: list[str] | None = None,
    off_codes: list[str] | None = None,
):
    return store.SwitchRecord(
        id="record-1",
        name="Test",
        channel=4,
        on_code=on_code,
        off_code=off_code,
        protocol=protocol_name,
        send_service="esphome.test",
        on_codes=on_codes or [on_code],
        off_codes=off_codes or [off_code],
    )


def make_hub(record):
    instance = object.__new__(hub_module.ESP32RFBridgeHub)
    instance.entry = types.SimpleNamespace(entry_id="test")
    instance.hass = types.SimpleNamespace()
    instance.store = FakeStore([record])
    instance._learn_target = None
    instance._learn_captured_codes = set()
    instance._learn_finish_unsub = None
    instance.last_received_code = ""
    instance.last_learned_code = ""
    instance.learning_status = ""
    return instance


def test_all_harju_on_variants_update_one_switch() -> None:
    family = protocol.HARJU_CODE_FAMILIES["a_on"]
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code=family.codes[0],
        off_code=protocol.HARJU_CODE_FAMILIES["a_off"].codes[0],
        on_codes=list(family.codes),
    )
    instance = make_hub(record)

    for code in family.codes:
        record.state = False
        asyncio.run(instance.async_receive_code(code))
        assert record.state is True


def test_all_harju_off_variants_update_one_switch() -> None:
    family = protocol.HARJU_CODE_FAMILIES["a_off"]
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code=protocol.HARJU_CODE_FAMILIES["a_on"].codes[0],
        off_code=family.codes[0],
        off_codes=list(family.codes),
    )
    instance = make_hub(record)

    for code in family.codes:
        record.state = True
        asyncio.run(instance.async_receive_code(code))
        assert record.state is False


def test_harju_tx_sends_all_four_variants() -> None:
    family = protocol.HARJU_CODE_FAMILIES["a_on"]
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code=family.codes[0],
        off_code=protocol.HARJU_CODE_FAMILIES["a_off"].codes[0],
        on_codes=list(family.codes),
    )
    instance = make_hub(record)
    sent: list[str] = []

    async def send_code(code: str, _service: str) -> None:
        sent.append(code)

    async def set_state(_record, is_on: bool) -> None:
        _record.state = is_on

    instance.async_send_code = send_code
    instance.async_set_record_state = set_state
    asyncio.run(instance.async_turn_record(record, True))

    assert sent == list(family.codes)
    assert record.state is True


def test_harju_off_tx_sends_all_four_variants() -> None:
    family = protocol.HARJU_CODE_FAMILIES["a_off"]
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code=protocol.HARJU_CODE_FAMILIES["a_on"].codes[0],
        off_code=family.codes[0],
        off_codes=list(family.codes),
    )
    instance = make_hub(record)
    sent: list[str] = []

    async def send_code(code: str, _service: str) -> None:
        sent.append(code)

    async def set_state(_record, is_on: bool) -> None:
        _record.state = is_on

    instance.async_send_code = send_code
    instance.async_set_record_state = set_state
    asyncio.run(instance.async_turn_record(record, False))

    assert sent == list(family.codes)
    assert record.state is False


def test_harju_learning_expands_one_known_code() -> None:
    family = protocol.HARJU_CODE_FAMILIES["a_on"]
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code="000000000000000000000001",
        off_code="000000000000000000000010",
    )
    instance = make_hub(record)

    stored = asyncio.run(
        instance._async_store_learned_code(
            record.id, const.LEARN_ON, family.codes[1], None
        )
    )

    assert stored is True
    assert record.incoming_on_codes == list(family.codes)
    assert record.on_codes == list(family.codes)


def test_known_harju_learning_still_finishes_after_family_expansion() -> None:
    family = protocol.HARJU_CODE_FAMILIES["a_on"]
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code="000000000000000000000001",
        off_code="000000000000000000000010",
    )
    instance = make_hub(record)
    instance._learn_target = (record.id, const.LEARN_ON, None)

    asyncio.run(instance.async_receive_code(family.codes[0]))

    assert instance._learn_target is None
    assert record.incoming_on_codes == list(family.codes)
    assert record.on_codes == list(family.codes)


def test_legacy_harju_record_migrates_known_alias_family() -> None:
    family = protocol.HARJU_CODE_FAMILIES["a_on"]
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code="000000000000000000000001",
        off_code="000000000000000000000010",
    )
    record.incoming_on_codes = [family.codes[2]]
    instance = make_hub(record)

    asyncio.run(instance._migrate_harju_code_families())

    assert record.incoming_on_codes == list(family.codes)
    assert record.on_codes == list(family.codes)


def test_legacy_record_without_code_lists_still_loads() -> None:
    record = store.SwitchRecord.from_dict(
        {
            "id": "legacy",
            "name": "Legacy Harju",
            "channel": 4,
            "on_code": "000000000000000000000001",
            "off_code": "000000000000000000000010",
            "protocol": const.PROTOCOL_HARJU,
            "send_service": "esphome.test",
            "incoming_on_codes": [],
            "incoming_off_codes": [],
        }
    )

    assert record.on_codes == [record.on_code]
    assert record.off_codes == [record.off_code]


def test_unknown_harju_learning_preserves_single_code() -> None:
    unknown = "000000000000000000000011"
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code="000000000000000000000001",
        off_code="000000000000000000000010",
    )
    instance = make_hub(record)

    stored = asyncio.run(
        instance._async_store_learned_code(
            record.id, const.LEARN_ON, unknown, None
        )
    )

    assert stored is True
    assert record.incoming_on_codes == [unknown]
    assert record.on_codes == [record.on_code]


def test_nexa_tx_and_rx_remain_single_code() -> None:
    on_code = "66695AA6A555965A"
    off_code = "66695AA6A555955A"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code=on_code,
        off_code=off_code,
    )
    instance = make_hub(record)
    sent: list[str] = []

    async def send_code(code: str, _service: str) -> None:
        sent.append(code)

    async def set_state(_record, is_on: bool) -> None:
        _record.state = is_on

    instance.async_send_code = send_code
    instance.async_set_record_state = set_state
    asyncio.run(instance.async_turn_record(record, True))
    assert sent == [on_code]

    record.state = False
    asyncio.run(instance.async_receive_code(on_code))
    assert record.state is True


def test_second_nexa_transmitter_can_be_learned_as_alias() -> None:
    second_remote_all_off = "6AA55A66AA599955"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    instance = make_hub(record)

    stored = asyncio.run(
        instance._async_store_learned_code(
            record.id, const.LEARN_OFF, second_remote_all_off, None
        )
    )

    assert stored is True
    assert record.incoming_off_codes == [second_remote_all_off]


def test_nexa_learning_finishes_after_first_valid_code() -> None:
    remote_on = "6AA55A66AA599655"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    instance = make_hub(record)
    instance._learn_target = (record.id, const.LEARN_ON, None)

    asyncio.run(instance.async_receive_code(remote_on))

    assert instance._learn_target is None
    assert record.incoming_on_codes == [remote_on]
    assert instance.learning_status == "Codes captured (1)"


def test_nexa_following_off_press_is_not_captured_into_on_learning() -> None:
    remote_on = "6AA55A66AA599655"
    remote_off = "6AA55A66AA599555"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    instance = make_hub(record)
    instance._learn_target = (record.id, const.LEARN_ON, None)

    asyncio.run(instance.async_receive_code(remote_on))
    asyncio.run(instance.async_receive_code(remote_off))

    assert record.incoming_on_codes == [remote_on]
    assert remote_off not in record.incoming_on_codes


def test_relearning_nexa_code_removes_it_from_opposite_list() -> None:
    remote_on = "6AA55A66AA599655"
    remote_off = "6AA55A66AA599555"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    record.incoming_on_codes = [remote_on, remote_off]
    record.incoming_off_codes = [remote_on, remote_off]
    instance = make_hub(record)

    asyncio.run(
        instance._async_store_learned_code(
            record.id, const.LEARN_ON, remote_on, None
        )
    )
    asyncio.run(
        instance._async_store_learned_code(
            record.id, const.LEARN_OFF, remote_off, None
        )
    )

    assert record.incoming_on_codes == [remote_on]
    assert record.incoming_off_codes == [remote_off]


def test_unknown_harju_learning_still_uses_capture_window() -> None:
    unknown = "000000000000000000000011"
    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code="000000000000000000000001",
        off_code="000000000000000000000010",
    )
    instance = make_hub(record)
    instance._learn_target = (record.id, const.LEARN_ON, None)

    asyncio.run(instance.async_receive_code(unknown))

    assert instance._learn_target == (record.id, const.LEARN_ON, None)
    assert record.incoming_on_codes == [unknown]


def test_second_nexa_all_off_is_learned_globally_and_survives_cleanup() -> None:
    second_remote_all_off = "6AA55A66AA599955"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    instance = make_hub(record)

    stored = asyncio.run(
        instance._async_store_learned_code(
            hub_module.ALL_SWITCHES_LEARN_TARGET,
            const.LEARN_OFF,
            second_remote_all_off,
            const.PROTOCOL_NEXA,
        )
    )
    asyncio.run(instance._cleanup_invalid_learned_codes())

    assert stored is True
    assert record.incoming_off_codes == [second_remote_all_off]


def test_two_nexa_transmitters_trigger_same_logical_off_action() -> None:
    first_remote_all_off = "66695AA6A5559955"
    second_remote_all_off = "6AA55A66AA599955"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    record.incoming_off_codes = [first_remote_all_off, second_remote_all_off]
    instance = make_hub(record)

    for code in record.incoming_off_codes:
        record.state = True
        asyncio.run(instance.async_receive_code(code))
        assert record.state is False


def test_nexa_text_sensor_result_does_not_depend_on_rcswitch_protocol() -> None:
    second_remote_all_off = "6AA55A66AA599955"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    instance = make_hub(record)
    instance._learn_target = (record.id, const.LEARN_OFF, None)

    asyncio.run(
        instance._async_receive_state_code(
            f"{second_remote_all_off} @ 81405410",
            "text_sensor.valojen_ohjaus_viimeisin_rf_koodi",
        )
    )

    assert record.incoming_off_codes == [second_remote_all_off]


def test_invalid_pair_coded_noise_is_not_accepted_as_nexa_alias() -> None:
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    instance = make_hub(record)

    stored = asyncio.run(
        instance._async_store_learned_code(
            record.id, const.LEARN_OFF, "FFFFFFFFFFFFFFFF", None
        )
    )

    assert stored is False
    assert record.incoming_off_codes == []


def test_current_send_action_is_preferred_over_legacy_action() -> None:
    """An upgraded ESPHome node wins even when a record contains the old action."""

    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    instance = make_hub(record)
    available = {const.DEFAULT_SEND_SERVICE}
    instance.hass.services = types.SimpleNamespace(
        has_service=lambda domain, service: f"{domain}.{service}" in available
    )

    selected = instance._resolve_send_service("esphome.valojen_ohjaus_rf_send")

    assert selected == const.DEFAULT_SEND_SERVICE


def test_legacy_send_action_is_used_until_esp32_is_renamed() -> None:
    """The English integration remains usable with the old ESPHome firmware."""

    record = make_record(
        protocol_name=const.PROTOCOL_HARJU,
        on_code="111111011011110100000101",
        off_code="111111110101011111010101",
    )
    instance = make_hub(record)
    legacy = "esphome.valojen_ohjaus_rf_send_harju"
    available = {legacy}
    instance.hass.services = types.SimpleNamespace(
        has_service=lambda domain, service: f"{domain}.{service}" in available
    )

    selected = instance._resolve_send_service(const.DEFAULT_HARJU_SEND_SERVICE)

    assert selected == legacy


def test_legacy_action_references_are_normalized_in_storage() -> None:
    """Stored switch and config references move to the current English action."""

    legacy = "esphome.valojen_ohjaus_rf_send"
    record = make_record(
        protocol_name=const.PROTOCOL_NEXA,
        on_code="66695AA6A555965A",
        off_code="66695AA6A555955A",
    )
    record.send_service = legacy
    instance = make_hub(record)
    instance.entry.data = {const.CONF_SEND_SERVICE: legacy}
    instance.entry.options = {}
    updates = []
    instance.hass.config_entries = types.SimpleNamespace(
        async_update_entry=lambda entry, **changes: updates.append((entry, changes))
    )

    asyncio.run(instance._normalize_esphome_action_references())

    assert record.send_service == const.DEFAULT_SEND_SERVICE
    assert instance.store.save_count == 1
    assert updates[0][1]["data"][const.CONF_SEND_SERVICE] == const.DEFAULT_SEND_SERVICE


if __name__ == "__main__":
    test_all_harju_on_variants_update_one_switch()
    test_all_harju_off_variants_update_one_switch()
    test_harju_tx_sends_all_four_variants()
    test_harju_off_tx_sends_all_four_variants()
    test_harju_learning_expands_one_known_code()
    test_known_harju_learning_still_finishes_after_family_expansion()
    test_legacy_harju_record_migrates_known_alias_family()
    test_legacy_record_without_code_lists_still_loads()
    test_unknown_harju_learning_preserves_single_code()
    test_nexa_tx_and_rx_remain_single_code()
    test_second_nexa_transmitter_can_be_learned_as_alias()
    test_nexa_learning_finishes_after_first_valid_code()
    test_nexa_following_off_press_is_not_captured_into_on_learning()
    test_relearning_nexa_code_removes_it_from_opposite_list()
    test_unknown_harju_learning_still_uses_capture_window()
    test_second_nexa_all_off_is_learned_globally_and_survives_cleanup()
    test_two_nexa_transmitters_trigger_same_logical_off_action()
    test_nexa_text_sensor_result_does_not_depend_on_rcswitch_protocol()
    test_invalid_pair_coded_noise_is_not_accepted_as_nexa_alias()
    test_current_send_action_is_preferred_over_legacy_action()
    test_legacy_send_action_is_used_until_esp32_is_renamed()
    test_legacy_action_references_are_normalized_in_storage()
    print("runtime assertions passed")
