"""Protocol capabilities exposed by ESP32 433 MHz RF Bridge V2."""

from __future__ import annotations

from dataclasses import dataclass

from .const import PROTOCOL_HARJU, PROTOCOL_NEXA


@dataclass(frozen=True)
class ProtocolCapabilities:
    """Features supported by one outlet protocol."""

    receive: bool
    learn_remote: bool
    learn_all_off: bool
    swap_transmit_polarity: bool


PROTOCOL_CAPABILITIES = {
    PROTOCOL_NEXA: ProtocolCapabilities(
        receive=True,
        learn_remote=True,
        learn_all_off=True,
        swap_transmit_polarity=False,
    ),
    PROTOCOL_HARJU: ProtocolCapabilities(
        receive=False,
        learn_remote=False,
        learn_all_off=False,
        swap_transmit_polarity=True,
    ),
}


def capabilities_for(protocol: str) -> ProtocolCapabilities:
    """Return capabilities for a supported protocol."""

    return PROTOCOL_CAPABILITIES[protocol]
