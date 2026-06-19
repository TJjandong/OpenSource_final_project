from __future__ import annotations

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


def start_lkm_writer_thread(target_uuid: str, device_path: str = "/dev/pico_tracker") -> None:
    import threading
    import struct
    import time

    # BLE thread 最後一次從 scan 收到合法 RSSI 的時間與值
    last_rssi: list[int | None] = [None]
    last_ble_update: list[float] = [0.0]

    # 超過此秒數沒有 scan 輸出合法 RSSI，判定斷線，寫哨兵
    DISCONNECT_TIMEOUT = 15.0

    # 心跳：每 3 秒把最新值寫入 LKM，維持 buffer 新鮮
    HEARTBEAT_INTERVAL = 3.0

    # scan restart：每 8 秒重啟一次掃描，強制 bluetoothctl 重新輸出所有裝置的 RSSI
    # bluetoothctl 在 RSSI 穩定時不會主動輸出，重啟可解決此問題
    # 注意：不使用 bluetoothctl info，因為它讀的是系統快取（即使裝置已斷電仍有資料）
    SCAN_RESTART_INTERVAL = 8.0

    def _heartbeat():
        """每 3 秒寫一次 LKM：
        - scan 最近有更新（< DISCONNECT_TIMEOUT）→ 寫入最新 RSSI
        - scan 長時間沉默 → 寫入哨兵值，GUI 顯示斷線
        核心模組 buffer 讀完不清空，心跳覆蓋最新值即可。"""
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            if last_rssi[0] is None:
                continue  # 尚未收到任何合法 RSSI，不寫入

            age = time.monotonic() - last_ble_update[0]
            if age < DISCONNECT_TIMEOUT:
                value = last_rssi[0]
                label = f"RSSI {value} dBm (scan {age:.1f}s ago)"
            else:
                value = DISCONNECT_SENTINEL
                label = f"SENTINEL (scan silent {age:.1f}s → disconnected)"

            try:
                with open(device_path, "wb") as f:
                    f.write(struct.pack("<i", value))
                print(f"[BLE Heartbeat] {label}", flush=True)
            except Exception as e:
                print(f"[BLE Heartbeat] Write failed: {e}", flush=True)

    def _scan_restarter(process_stdin):
        """每 8 秒重啟 bluetoothctl scan，強制重新輸出所有鄰近裝置的 RSSI。
        不使用 bluetoothctl info（會讀快取舊資料，即使 Pico 已斷電）。"""
        time.sleep(SCAN_RESTART_INTERVAL)  # 先等初始 scan 穩定
        while True:
            try:
                process_stdin.write("scan off\n")
                process_stdin.flush()
                time.sleep(1.0)
                process_stdin.write("scan on\n")
                process_stdin.flush()
                print("[BLE Scan] Restarted scan → fresh RSSI reports.", flush=True)
            except Exception as e:
                print(f"[BLE Scan] Restart failed: {e}", flush=True)
                break
            time.sleep(SCAN_RESTART_INTERVAL)

    def _run_writer():
        import subprocess
        import re

        print("[BLE Background] Starting bluetoothctl wrapper...", flush=True)

        target_macs: set[str] = set()

        try:
            process = subprocess.Popen(
                ['bluetoothctl'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # 查詢已記住的裝置，再開掃描
            process.stdin.write("devices\n")
            process.stdin.flush()
            process.stdin.write("scan on\n")
            process.stdin.flush()

            # 啟動 scan restart thread
            restart_t = threading.Thread(
                target=_scan_restarter,
                args=(process.stdin,),
                daemon=True
            )
            restart_t.start()

            devices_re = re.compile(r"Device ([0-9a-fA-F:]+) (.*)")
            new_device_re = re.compile(r"\[(?:NEW|CHG)\] Device ([0-9a-fA-F:]+) (.*)")

            while True:
                line = process.stdout.readline()
                if not line:
                    break
                line = line.strip()

                # 從 'devices' 輸出找已記住的裝置
                if line.startswith("Device"):
                    m = devices_re.match(line)
                    if m:
                        mac, name = m.groups()
                        if ("pico" in name.lower() or "tracker" in name.lower()) and mac not in target_macs:
                            print(f"[BLE Background] Known target: {mac} ({name})", flush=True)
                            target_macs.add(mac)

                # 從掃描輸出找新裝置
                nm = new_device_re.search(line)
                if nm:
                    mac, rest = nm.group(1), nm.group(2)
                    if ("pico" in rest.lower() or "tracker" in rest.lower()) and mac not in target_macs:
                        print(f"[BLE Background] Discovered: {mac} ({rest})", flush=True)
                        target_macs.add(mac)

                # 解析 RSSI（只接受來自真實廣播掃描的更新）
                if "RSSI:" in line:
                    parts = line.split()
                    if len(parts) >= 4 and parts[1] == "Device":
                        mac = parts[2]
                        if mac in target_macs:
                            if "(" in line and ")" in line:
                                rssi_str = line.split("(")[-1].split(")")[0]
                            else:
                                rssi_str = line.split("RSSI:")[1].strip()
                            try:
                                rssi = int(rssi_str)
                                if not _is_valid_rssi(rssi):
                                    print(f"[BLE Background] Ignored invalid RSSI: {rssi} dBm", flush=True)
                                    continue
                                print(f"[BLE Background] Valid RSSI: {rssi} dBm for {mac}", flush=True)
                                last_rssi[0] = rssi
                                last_ble_update[0] = time.monotonic()
                                with open(device_path, "wb") as f:
                                    f.write(struct.pack("<i", rssi))
                            except Exception as e:
                                print(f"[BLE Background] Parse/write failed: {e}", flush=True)

        except Exception as e:
            print(f"[BLE Background] bluetoothctl wrapper failed: {e}", flush=True)

    heartbeat_t = threading.Thread(target=_heartbeat, daemon=True)
    heartbeat_t.start()

    t = threading.Thread(target=_run_writer, daemon=True)
    t.start()
