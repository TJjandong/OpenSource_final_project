from __future__ import annotations

# NOTE: fcntl / struct / os imports removed.
# BLE scanning is now performed inside the Linux Kernel Module (pico_tracker.c)
# via a kernel-space HCI socket. Python only reads RSSI via ioctl (IoctlSignalSource).

import asyncio
import random
import fcntl
import struct
import os
from abc import ABC, abstractmethod

# _IOR('p', 1, int) definition for Linux ioctl
PICO_GET_RSSI = (2 << 30) | (4 << 16) | (112 << 8) | 1

# 哨兵值：BLE thread 在偵測到 Pico 斷線時寫入此值
# 遠超出正常 RSSI 範圍（-120 ~ -1 dBm），讓 GUI 明確判斷斷線
DISCONNECT_SENTINEL = -9999

# 合法 RSSI 範圍：BLE RSSI 不可能是 0 或正數
RSSI_MIN, RSSI_MAX = -120, -1


def _is_valid_rssi(rssi: int) -> bool:
    return RSSI_MIN <= rssi <= RSSI_MAX


class BeaconNotFoundError(RuntimeError):
    """Raised when Pico is disconnected or out of range."""


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
                buf = bytearray(4)
                try:
                    fcntl.ioctl(f.fileno(), PICO_GET_RSSI, buf)
                    rssi = struct.unpack("i", buf)[0]

                    # 哨兵值：BLE thread 判定 Pico 斷線時寫入此值
                    if rssi <= DISCONNECT_SENTINEL:
                        print(f"[GUI Read] Sentinel {rssi} detected → Pico disconnected.", flush=True)
                        raise BeaconNotFoundError("Pico disconnected (sentinel in LKM)")

                    # 過濾無效 RSSI（例如 0 dBm 為系統 buffer 初始值或快取錯誤）
                    if not _is_valid_rssi(rssi):
                        print(f"[GUI Read] Invalid RSSI {rssi} dBm ignored (not in {RSSI_MIN}~{RSSI_MAX}).", flush=True)
                        raise BeaconNotFoundError(f"Invalid RSSI value {rssi} dBm")

                    print(f"[GUI Read] RSSI from LKM: {rssi} dBm", flush=True)
                    return int(rssi)

                except OSError as e:
                    if e.errno == 61:  # ENODATA：buffer 從未有資料（剛啟動）
                        print("[GUI Read] ENODATA: buffer empty, Pico not yet seen.", flush=True)
                        raise BeaconNotFoundError("Pico not yet seen: LKM buffer empty") from e
                    raise RuntimeError(f"ioctl failed on {self.device_path}: {e}") from e

        except BeaconNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to read from {self.device_path}: {e}") from e


# ── start_lkm_writer_thread() 已移除 ──
#
# 原本此函式負責：
#   1. 以 subprocess 啟動 bluetoothctl
#   2. 解析 RSSI 輸出
#   3. 將 RSSI 寫入 /dev/pico_tracker
#
# 現在這些工作全部由核心模組內的 BLE kthread 完成：
#   - kernel_module/pico_tracker.c: ble_scan_thread_fn()
#   - 透過 HCI kernel socket 直接控制 hci0
#   - 不需要任何 User Space BLE 程式
#
# Python 只需用 IoctlSignalSource 透過 ioctl 讀取 RSSI 即可。
