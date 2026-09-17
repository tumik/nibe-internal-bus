"""UDP transport and value store for the Nibe internal RS-485 bus.

READ-ONLY BY DESIGN. The only thing this integration ever transmits is the
zero-length trigger packet from :mod:`.protocol`, which exists solely to
register this host in the ESP32's UDP target list. That packet is tagged
MODBUS40/READ_TOKEN by which port it arrives on, and with the ESPHome device's
``acknowledge:`` list empty it is never dequeued onto the RS-485 bus. Do not
add a write path here -- doing so would start injecting traffic into the live
bus between the heat pump's mainboard and its display.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections import Counter
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    BUS_ADDRESS,
    DISCRETE_FIELDS,
    DOMAIN,
    FIELD_COMPRESSOR,
    FIELD_OPERATING_MODE,
    FIELD_THREE_WAY_VALVE,
    KEEPALIVE_INTERVAL,
    MODE_HEATING,
    MODE_HOT_WATER,
    MODE_STANDBY,
    PROBE_TIMEOUT,
    STALE_AFTER,
)
from .decoder import decode_frame
from .protocol import TRIGGER_PACKET, parse_frames

_LOGGER = logging.getLogger(__name__)


def operating_mode(compressor: int, valve: int) -> str:
    """Map the relay bits to the mode the pump is actually in."""
    if not compressor:
        return MODE_STANDBY
    return MODE_HOT_WATER if valve else MODE_HEATING


class CannotConnect(Exception):
    """No datagram arrived from the nibegw device."""


class NoValidFrames(Exception):
    """Datagrams arrived but nothing in them parsed as a bus frame."""


class NoPumpData(Exception):
    """Frames parsed but none came from the heat pump's bus address."""


class _UdpProtocol(asyncio.DatagramProtocol):
    """Hands every received datagram to a callback."""

    def __init__(self, on_datagram) -> None:
        self._on_datagram = on_datagram

    def datagram_received(self, data: bytes, addr) -> None:
        self._on_datagram(data)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)


async def _async_resolve(hass: HomeAssistant, host: str, port: int) -> tuple[str, int]:
    """Resolve the nibegw host once, so sends never block the event loop."""
    infos = await hass.loop.getaddrinfo(
        host, port, family=socket.AF_INET, type=socket.SOCK_DGRAM
    )
    return infos[0][4][:2]


async def async_probe(hass: HomeAssistant, host: str, port: int) -> None:
    """Verify that the given host actually forwards internal-bus frames."""
    try:
        target = await _async_resolve(hass, host, port)
    except OSError as err:
        raise CannotConnect from err

    received = asyncio.Event()
    parsed = asyncio.Event()
    matched = asyncio.Event()

    @callback
    def on_datagram(data: bytes) -> None:
        received.set()
        frames = [frame for frame in parse_frames(data) if frame.checksum_ok]
        if frames:
            parsed.set()
        if any(frame.address == BUS_ADDRESS for frame in frames):
            matched.set()

    try:
        transport, _ = await hass.loop.create_datagram_endpoint(
            lambda: _UdpProtocol(on_datagram),
            local_addr=("0.0.0.0", 0),
            family=socket.AF_INET,
        )
    except OSError as err:
        raise CannotConnect from err

    try:
        transport.sendto(TRIGGER_PACKET, target)
        try:
            async with asyncio.timeout(PROBE_TIMEOUT):
                await matched.wait()
        except TimeoutError:
            if not received.is_set():
                raise CannotConnect from None
            if not parsed.is_set():
                raise NoValidFrames from None
            raise NoPumpData from None
    finally:
        transport.close()


class NibeInternalBusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keeps this host registered with nibegw and decodes what it sends back."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        host: str,
        port: int,
        push_interval: int,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry)
        self.host = host
        self.port = port
        self.values: dict[str, Any] = {}
        self.last_datagram: float | None = None
        self.last_datagram_utc: datetime | None = None
        self.frame_counts: Counter[str] = Counter()
        self.checksum_errors = 0
        self.last_raw: bytes | None = None

        self._push_interval = push_interval
        self._seen: dict[str, float] = {}
        self._target: tuple[str, int] | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._unsub_timer = None
        self._first_data = asyncio.Event()

    async def _async_update_data(self) -> dict[str, Any]:
        """Return the latest snapshot; data arrives by push, never by polling."""
        return dict(self.values)

    async def async_start(self) -> None:
        """Open the socket, register with the device and start publishing."""
        self._target = await _async_resolve(self.hass, self.host, self.port)
        self._transport, _ = await self.hass.loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self._handle_datagram),
            local_addr=("0.0.0.0", 0),
            family=socket.AF_INET,
        )
        self._keepalive_task = self.config_entry.async_create_background_task(
            self.hass, self._keepalive(), f"{DOMAIN}_keepalive"
        )
        self._unsub_timer = async_track_time_interval(
            self.hass, self._handle_tick, timedelta(seconds=self._push_interval)
        )

    async def async_wait_for_data(self, timeout: float = PROBE_TIMEOUT) -> bool:
        """Wait for the first decoded frame after startup."""
        try:
            async with asyncio.timeout(timeout):
                await self._first_data.wait()
        except TimeoutError:
            return False
        return True

    async def async_stop(self) -> None:
        """Tear down the socket and timers."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def is_fresh(self, field_id: str) -> bool:
        """Whether this field has been seen recently enough to trust."""
        seen = self._seen.get(field_id)
        return seen is not None and monotonic() - seen <= STALE_AFTER

    async def _keepalive(self) -> None:
        """Re-register as a UDP target well before the device's 120 s timeout."""
        while True:
            try:
                if self._target is None:
                    self._target = await _async_resolve(self.hass, self.host, self.port)
                if self._transport is not None:
                    self._transport.sendto(TRIGGER_PACKET, self._target)
            except OSError as err:
                _LOGGER.debug("Keepalive to %s failed: %s", self.host, err)
                self._target = None
            await asyncio.sleep(KEEPALIVE_INTERVAL)

    @callback
    def _handle_datagram(self, data: bytes) -> None:
        now = monotonic()
        self.last_datagram = now
        self.last_datagram_utc = dt_util.utcnow()
        self.last_raw = data

        publish_now = False
        for frame in parse_frames(data):
            if not frame.checksum_ok:
                self.checksum_errors += 1
                continue
            if frame.address != BUS_ADDRESS:
                continue

            self.frame_counts[f"{frame.direction} {frame.cmd:02X}"] += 1

            for field_id, value in decode_frame(frame).items():
                if field_id in DISCRETE_FIELDS and self.values.get(field_id) != value:
                    publish_now = True
                self.values[field_id] = value
                self._seen[field_id] = now

            publish_now |= self._handle_derived()

        if self.values and not self._first_data.is_set():
            self._first_data.set()
            publish_now = True

        if publish_now:
            self._publish()

    @callback
    def _handle_derived(self) -> bool:
        """Derive the operating mode, which no payload carries directly.

        The compressor bit says whether the pump is producing anything at all,
        and the 3-way valve says where that production goes. The polled
        command (0x96 / 0x99) only tracks compressor state, not demand: 0x99
        was polled throughout a 30 minute run with the valve set to heating.
        """
        if FIELD_COMPRESSOR not in self._seen:
            return False

        mode = operating_mode(
            self.values[FIELD_COMPRESSOR], self.values[FIELD_THREE_WAY_VALVE]
        )
        changed = self.values.get(FIELD_OPERATING_MODE) != mode
        self.values[FIELD_OPERATING_MODE] = mode
        self._seen[FIELD_OPERATING_MODE] = self._seen[FIELD_COMPRESSOR]
        return changed

    @callback
    def _handle_tick(self, _now) -> None:
        self._publish()

    @callback
    def _publish(self) -> None:
        self.async_set_updated_data(dict(self.values))
