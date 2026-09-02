"""Tests for ESP32 433 MHz RF Bridge protocol helpers."""

from pathlib import Path
import importlib.util
import sys


def _load_protocol_module():
    path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "esp32_433mhz_rf_bridge"
        / "protocol.py"
    )
    spec = importlib.util.spec_from_file_location("esp32_433mhz_rf_bridge_protocol_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


protocol = _load_protocol_module()


def test_decode_confirmed_codes() -> None:
    """Known captures decode to the values observed during testing."""

    assert protocol.decode_manchester_64("66695AA6A5559655") == 0x563DC090
    assert protocol.decode_manchester_64("66695AA6A5559555") == 0x563DC080
    assert protocol.decode_manchester_64("66695AA6A555965A") == 0x563DC093
    assert protocol.decode_manchester_64("66695AA6A555955A") == 0x563DC083


def test_encode_roundtrip() -> None:
    """Encoding and decoding preserve a 32-bit command value."""

    value = 0x563DC093
    assert protocol.decode_manchester_64(protocol.encode_manchester_64(value)) == value


def test_generate_code_pair_channel_4() -> None:
    """Generated channel 4 matches the successfully tested virtual codes."""

    pair = protocol.generate_code_pair(4, "563DC0")
    assert pair.on_code == "66695AA6A555965A"
    assert pair.off_code == "66695AA6A555955A"


def test_nexa_transmitter_id() -> None:
    """Nexa transmitter id is decoded from the 64-bit RF code."""

    assert protocol.nexa_transmitter_id("66695AA6A5559955") == "563DC0"
    assert protocol.nexa_transmitter_id("6AA55A66AA599955") == "7C35F2"


def test_generate_harju_channel_b_pair() -> None:
    """Generated Harju channel B matches the tested outdoor outlet codes."""

    pair = protocol.generate_harju_channel_b_pair()
    assert pair.channel == 2
    assert pair.on_code == "111111011011110100000101"
    assert pair.off_code == "111111110101011111010101"


def test_generate_harju_code_pair_channel_b() -> None:
    """Generated Harju channel 2 preserves the tested channel B codes."""

    pair = protocol.generate_harju_code_pair(2)
    assert pair.channel == 2
    assert pair.on_code == "111111011011110100000101"
    assert pair.off_code == "111111110101011111010101"


def test_generate_harju_code_pair_channels_are_unique() -> None:
    """Different generated Harju channels must not reuse the same RF codes."""

    channel_4 = protocol.generate_harju_code_pair(4)
    channel_5 = protocol.generate_harju_code_pair(5)
    assert channel_4.on_code != channel_5.on_code
    assert channel_4.off_code != channel_5.off_code
    assert channel_4.on_code != "111111011011110100000101"
    assert channel_4.off_code != "111111110101011111010101"


def test_generate_harju_non_b_channels_use_observed_pairing_polarity() -> None:
    """Generated non-B Harju channels use the polarity observed while pairing."""

    channel_4 = protocol.generate_harju_code_pair(4)
    assert channel_4.on_code == "111111110101011111010011"
    assert channel_4.off_code == "111111011011110100000011"


def test_expand_harju_a_on_family() -> None:
    """Any known A ON phase expands to the complete four-code family."""

    expected = (
        "111110111010101100011100",
        "111100111001100001011100",
        "111111000011111010101100",
        "111100010100000001101100",
    )
    for code in expected:
        assert protocol.expand_harju_code(code) == expected
        family = protocol.classify_harju_code(code)
        assert family is not None
        assert family.key == "a_on"
        assert family.command == "on"


def test_expand_harju_a_off_family() -> None:
    """Any known A OFF phase expands to the complete four-code family."""

    expected = (
        "111101010000101001111100",
        "111111100001001100101100",
        "111100001101110010001100",
        "111100100010010110111100",
    )
    for code in expected:
        assert protocol.expand_harju_code(code) == expected
        family = protocol.classify_harju_code(code)
        assert family is not None
        assert family.key == "a_off"
        assert family.command == "off"


def test_unknown_harju_code_is_not_expanded() -> None:
    """A valid but unknown Harju code must never produce guessed variants."""

    code = "000000000000000000000001"
    assert protocol.classify_harju_code(code) is None
    assert protocol.expand_harju_code(code) is None


def test_normalize_rf_code_accepts_nexa_and_harju() -> None:
    """Incoming RF normalization accepts both supported code formats."""

    assert protocol.normalize_rf_code("66695aa6a555965a") == "66695AA6A555965A"
    assert (
        protocol.normalize_rf_code("111111011011110100000101")
        == "111111011011110100000101"
    )


if __name__ == "__main__":
    test_decode_confirmed_codes()
    test_encode_roundtrip()
    test_generate_code_pair_channel_4()
    test_nexa_transmitter_id()
    test_generate_harju_channel_b_pair()
    test_generate_harju_code_pair_channel_b()
    test_generate_harju_code_pair_channels_are_unique()
    test_generate_harju_non_b_channels_use_observed_pairing_polarity()
    test_expand_harju_a_on_family()
    test_expand_harju_a_off_family()
    test_unknown_harju_code_is_not_expanded()
    test_normalize_rf_code_accepts_nexa_and_harju()
    print("protocol assertions passed")
