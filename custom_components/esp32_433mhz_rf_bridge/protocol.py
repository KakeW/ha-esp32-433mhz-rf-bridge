"""Protocol helpers for the learned 433.92 MHz outlet codes."""

from __future__ import annotations

from dataclasses import dataclass
import re


HEX64_RE = re.compile(r"^[0-9a-fA-F]{16}$")
BIN24_RE = re.compile(r"^[01]{24}$")
TRANSMITTER_RE = re.compile(r"^[0-9a-fA-F]{6}$")
HARJU_CHANNEL_B_ON = "111111011011110100000101"
HARJU_CHANNEL_B_OFF = "111111110101011111010101"

HARJU_CODE_FAMILIES_DATA: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "a_on": (
        "A",
        "on",
        (
            "111110111010101100011100",
            "111100111001100001011100",
            "111111000011111010101100",
            "111100010100000001101100",
        ),
    ),
    "a_off": (
        "A",
        "off",
        (
            "111101010000101001111100",
            "111111100001001100101100",
            "111100001101110010001100",
            "111100100010010110111100",
        ),
    ),
    "b_on": (
        "B",
        "on",
        (
            "111111011011110100000101",
            "111110001110011000110101",
            "111101000111000111110101",
            "111101110110111111100101",
        ),
    ),
    "b_off": (
        "B",
        "off",
        (
            "111110011111001010010101",
            "111111110101011111010101",
            "111101101000100101000101",
            "111110101100010011000101",
        ),
    ),
    "c_on": (
        "C",
        "on",
        (
            "111101010000101001111110",
            "111111100001001100101110",
            "111100001101110010001110",
            "111100100010010110111110",
        ),
    ),
    "c_off": (
        "C",
        "off",
        (
            "111110111010101100011110",
            "111100111001100001011110",
            "111111000011111010101110",
            "111100010100000001101110",
        ),
    ),
    "all_on": (
        "ALL",
        "on",
        (
            "111100100010010110110010",
            "111100001101110010000010",
            "111111100001001100100010",
            "111101010000101001110010",
        ),
    ),
    "all_off": (
        "ALL",
        "off",
        (
            "111100010100000001100010",
            "111111000011111010100010",
            "111100111001100001010010",
            "111110111010101100010010",
        ),
    ),
}


class ProtocolError(ValueError):
    """Raised when an RF code cannot be generated or parsed."""


@dataclass(frozen=True)
class CodePair:
    """ON/OFF code pair for one virtual channel."""

    channel: int
    on_code: str
    off_code: str


@dataclass(frozen=True)
class HarjuCodeFamily:
    """One known four-variant command from the tested Harju remote."""

    key: str
    channel: str
    command: str
    codes: tuple[str, ...]

    @property
    def is_all(self) -> bool:
        """Return whether the family is an ALL command."""

        return self.channel == "ALL"


HARJU_CODE_FAMILIES: dict[str, HarjuCodeFamily] = {
    key: HarjuCodeFamily(key, channel, command, codes)
    for key, (channel, command, codes) in HARJU_CODE_FAMILIES_DATA.items()
}
HARJU_CODE_INDEX: dict[str, HarjuCodeFamily] = {
    code: family
    for family in HARJU_CODE_FAMILIES.values()
    for code in family.codes
}


def normalize_hex64(code: str) -> str:
    """Normalize a 64-bit hex code."""

    compact = "".join(str(code).split()).upper()
    if not HEX64_RE.fullmatch(compact):
        raise ProtocolError("RF code must be exactly 16 hexadecimal characters")
    return compact


def normalize_bin24(code: str) -> str:
    """Normalize a 24-bit binary RF code."""

    compact = "".join(str(code).split())
    if not BIN24_RE.fullmatch(compact):
        raise ProtocolError("Harju RF code must be exactly 24 binary characters")
    return compact


def classify_harju_code(code: str) -> HarjuCodeFamily | None:
    """Return the known Harju command family for a received code, if any."""

    try:
        normalized = normalize_bin24(code)
    except ProtocolError:
        return None
    return HARJU_CODE_INDEX.get(normalized)


def expand_harju_code(code: str) -> tuple[str, ...] | None:
    """Expand one known Harju code to its four variants without guessing."""

    family = classify_harju_code(code)
    return family.codes if family is not None else None


def normalize_rf_code(code: str) -> str:
    """Normalize either a Nexa 64-bit hex code or a Harju 24-bit binary code."""

    compact = "".join(str(code).split()).upper()
    if HEX64_RE.fullmatch(compact):
        return compact
    if BIN24_RE.fullmatch(compact):
        return compact
    raise ProtocolError(
        "RF code must be 16 hexadecimal characters or 24 binary characters"
    )


def normalize_transmitter_id(transmitter_id: str) -> str:
    """Normalize the observed 24-bit transmitter id."""

    compact = "".join(str(transmitter_id).split()).upper()
    if not TRANSMITTER_RE.fullmatch(compact):
        raise ProtocolError("Transmitter id must be exactly 6 hexadecimal characters")
    return compact


def encode_manchester_64(value: int) -> str:
    """Encode a 32-bit value into the observed 64-bit pair-coded RF hex string.

    Observed captures only contain bit pairs 01 and 10. The confirmed examples map
    decoded 32-bit bit 0 -> pair 01 and bit 1 -> pair 10.
    """

    if value < 0 or value > 0xFFFFFFFF:
        raise ProtocolError("Value must fit in 32 bits")

    encoded = 0
    for bit_index in range(31, -1, -1):
        bit = (value >> bit_index) & 1
        pair = 0b10 if bit else 0b01
        encoded = (encoded << 2) | pair
    return f"{encoded:016X}"


def decode_manchester_64(code: str) -> int:
    """Decode an observed 64-bit pair-coded RF hex string into a 32-bit value."""

    encoded = int(normalize_hex64(code), 16)
    value = 0
    for pair_index in range(31, -1, -1):
        pair = (encoded >> (pair_index * 2)) & 0b11
        if pair == 0b01:
            bit = 0
        elif pair == 0b10:
            bit = 1
        else:
            raise ProtocolError("RF code is not valid pair-coded data")
        value = (value << 1) | bit
    return value


def nexa_transmitter_id(code: str) -> str:
    """Return the 24-bit transmitter id from a Nexa 64-bit RF code."""

    value = decode_manchester_64(code)
    return f"{value >> 8:06X}"


def generate_code_pair(channel: int, transmitter_id: str = "563DC0") -> CodePair:
    """Generate ON/OFF RF codes for a virtual channel.

    Basis from the tested captures:
    - 1 ON  -> decoded 0x563DC090 -> encoded 66695AA6A5559655
    - 1 OFF -> decoded 0x563DC080 -> encoded 66695AA6A5559555
    - 4 ON/OFF were tested successfully with decoded suffixes 0x93/0x83.

    The current generator therefore uses decoded suffixes:
    - ON:  0x8F + channel
    - OFF: 0x7F + channel
    """

    if channel < 1 or channel > 112:
        raise ProtocolError("Channel must be between 1 and 112")

    base = int(normalize_transmitter_id(transmitter_id), 16) << 8
    on_value = base | (0x8F + channel)
    off_value = base | (0x7F + channel)
    return CodePair(
        channel=channel,
        on_code=encode_manchester_64(on_value),
        off_code=encode_manchester_64(off_value),
    )


def generate_harju_channel_b_pair() -> CodePair:
    """Return the confirmed Harju channel B ON/OFF codes."""

    return CodePair(
        channel=2,
        on_code=HARJU_CHANNEL_B_ON,
        off_code=HARJU_CHANNEL_B_OFF,
    )


def generate_harju_code_pair(channel: int) -> CodePair:
    """Generate a deterministic Harju/RCSwitch 24-bit ON/OFF code pair."""

    if channel < 1 or channel > 255:
        raise ProtocolError("Harju channel must be between 1 and 255")

    offset = channel ^ 2
    on_value = int(HARJU_CHANNEL_B_ON, 2) ^ offset
    off_value = int(HARJU_CHANNEL_B_OFF, 2) ^ offset

    if channel != 2:
        # Observed generated Harju pairs are opposite polarity when paired.
        on_value, off_value = off_value, on_value

    return CodePair(
        channel=channel,
        on_code=f"{on_value:024b}",
        off_code=f"{off_value:024b}",
    )
