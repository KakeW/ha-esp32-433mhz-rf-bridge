"""Persistent switch registry for ESP32 433 MHz RF Bridge."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_SEND_SERVICE,
    PROTOCOL_NEXA,
    STORAGE_KEY,
    STORAGE_SCHEMA_VERSION,
    STORAGE_VERSION,
)


@dataclass
class SwitchRecord:
    """Stored configuration for one RF-controlled switch."""

    id: str
    name: str
    channel: int
    on_code: str
    off_code: str
    protocol: str = PROTOCOL_NEXA
    send_service: str = DEFAULT_SEND_SERVICE
    on_codes: list[str] = field(default_factory=list)
    off_codes: list[str] = field(default_factory=list)
    incoming_on_codes: list[str] = field(default_factory=list)
    incoming_off_codes: list[str] = field(default_factory=list)
    transmit_codes_swapped: bool = False
    state: bool | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SwitchRecord":
        """Create a record from stored data."""

        on_code = str(data["on_code"])
        off_code = str(data["off_code"])
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            channel=int(data["channel"]),
            on_code=on_code,
            off_code=off_code,
            protocol=str(data.get("protocol", PROTOCOL_NEXA)),
            send_service=str(data.get("send_service", DEFAULT_SEND_SERVICE)),
            on_codes=_unique_codes(data.get("on_codes", [on_code]), on_code),
            off_codes=_unique_codes(data.get("off_codes", [off_code]), off_code),
            incoming_on_codes=list(data.get("incoming_on_codes", [])),
            incoming_off_codes=list(data.get("incoming_off_codes", [])),
            transmit_codes_swapped=bool(data.get("transmit_codes_swapped", False)),
            state=data.get("state"),
        )


class RFStore:
    """Small storage wrapper for RF switch records."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""

        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.records: dict[str, SwitchRecord] = {}

    async def async_load(self) -> None:
        """Load stored switch records."""

        data = await self._store.async_load() or {}
        self.records = {
            record.id: record
            for record in (
                SwitchRecord.from_dict(item) for item in data.get("switches", [])
            )
        }

    async def async_save(self) -> None:
        """Persist switch records."""

        await self._store.async_save(
            {
                "schema_version": STORAGE_SCHEMA_VERSION,
                "switches": [asdict(record) for record in self.records.values()],
            }
        )

    def next_channel(self, first_channel: int) -> int:
        """Return the next unused virtual channel."""

        used_channels = {record.channel for record in self.records.values()}
        channel = first_channel
        while channel in used_channels:
            channel += 1
        return channel

    def add_record(
        self,
        *,
        name: str,
        channel: int,
        on_code: str,
        off_code: str,
        protocol: str = PROTOCOL_NEXA,
        send_service: str = DEFAULT_SEND_SERVICE,
        on_codes: list[str] | None = None,
        off_codes: list[str] | None = None,
    ) -> SwitchRecord:
        """Add a new switch record."""

        record = SwitchRecord(
            id=uuid4().hex,
            name=name,
            channel=channel,
            on_code=on_code,
            off_code=off_code,
            protocol=protocol,
            send_service=send_service,
            on_codes=_unique_codes(on_codes or [on_code], on_code),
            off_codes=_unique_codes(off_codes or [off_code], off_code),
            incoming_on_codes=[],
            incoming_off_codes=[],
        )
        self.records[record.id] = record
        return record

    def remove_record(self, record_id: str) -> SwitchRecord | None:
        """Remove a switch record."""

        return self.records.pop(record_id, None)


def _unique_codes(codes: Any, fallback: str) -> list[str]:
    """Return stored codes in stable order, falling back to the legacy code."""

    values = codes if isinstance(codes, list) else [fallback]
    normalized = list(dict.fromkeys(str(code) for code in values if str(code)))
    return normalized or [fallback]
