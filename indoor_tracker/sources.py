from __future__ import annotations

import asyncio
import random
import fcntl
import struct
import os
from abc import ABC, abstractmethod

# _IOR('p', 1, int) definition for Linux ioctl
PICO_GET_RSSI = (2 << 30) | (4 << 16) | (112 << 8) | 1


class SignalSource(ABC):
    @abstractmethod
    def read(self) -> int:
        raise NotImplementedError


class SimulatedSignalSource(SignalSource):
    def __init__(self, base_rssi: int = -58, noise: int = 4, drift: float = 0.6) -> None:
        self.base_rssi = base_rssi
        self.noise = noise
        self.drift = drift
        self._current = float(base_rssi)

    def read(self) -> int:
        self._current += random.uniform(-self.drift, self.drift)
        self._current += random.gauss(0, self.noise / 3)
        self._current = max(-95.0, min(-35.0, self._current))
        if random.random() < 0.08:
            self._current -= random.uniform(3, 8)
        return int(round(self._current))


class BleSignalSource(SignalSource):
    def __init__(self, target_uuid: str, timeout: float = 1.5) -> None:
        self.target_uuid = target_uuid.lower()
        self.timeout = timeout

    def read(self) -> int:
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise RuntimeError("bleak is not installed") from exc

        return asyncio.run(self._scan_once(BleakScanner))

    async def _scan_once(self, scanner_cls) -> int:
        devices = await scanner_cls.discover(timeout=self.timeout)
        for device in devices:
            uuids = device.metadata.get("uuids") or []
            normalized = [uuid.lower() for uuid in uuids]
            if self.target_uuid in normalized:
                if device.rssi is not None:
                    return int(device.rssi)
        raise RuntimeError("target beacon not found during scan")


class IoctlSignalSource(SignalSource):
    def __init__(self, device_path: str = "/dev/pico_tracker") -> None:
        self.device_path = device_path
        if not os.path.exists(self.device_path):
            raise FileNotFoundError(f"Device {self.device_path} not found. Is the LKM loaded?")

    def read(self) -> int:
        try:
            with open(self.device_path, "r") as f:
                # Prepare a buffer for the integer output (4 bytes)
                buf = bytearray(4)
                # Call ioctl
                fcntl.ioctl(f.fileno(), PICO_GET_RSSI, buf)
                # Unpack the integer from the buffer
                rssi = struct.unpack("i", buf)[0]
                return int(rssi)
        except OSError as e:
            # Handle ENODATA or other errors
            raise RuntimeError(f"ioctl failed on {self.device_path}: {e}") from e

