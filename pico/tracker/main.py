import bluetooth
import time
import struct

# 設定專題使用的 UUID (使用 128-bit 自訂 UUID 或是標準的短 UUID)
# 這裡使用一個自訂的 16-bit UUID，並轉換成廣播格式
_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID16_COMPLETE = const(0x03)

# 設備名稱
name = "Pico-Tracker"

# 16-bit UUID: 0xFEED (Matches the host config target_uuid 0000FEED-...)
uuid16 = 0xFEED

# 建構廣播負載 (Advertising Payload)
def build_advertising_payload(name, uuid16):
    payload = bytearray()
    
    # 1. Flags
    payload.append(2)
    payload.append(_ADV_TYPE_FLAGS)
    payload.append(0x06) # LE General Discoverable Mode | BR/EDR Not Supported
    
    # 2. Complete 16-bit UUIDs
    payload.append(3)
    payload.append(_ADV_TYPE_UUID16_COMPLETE)
    payload.extend(struct.pack("<H", uuid16))
    
    # 3. Complete Local Name
    name_bytes = name.encode("utf-8")
    payload.append(len(name_bytes) + 1)
    payload.append(_ADV_TYPE_NAME)
    payload.extend(name_bytes)
    
    return payload

def main():
    print("Initializing BLE...")
    ble = bluetooth.BLE()
    ble.active(True)
    
    payload = build_advertising_payload(name, uuid16)
    
    # 設定廣播間隔 (單位: 微秒)，這裡設為 100 毫秒 (100,000 us) 以確保即時性
    adv_interval_us = 100000 
    
    print(f"Starting BLE GAP Advertising as '{name}'...")
    print(f"UUID: 0x{uuid16:04X}")
    
    # 開始廣播
    ble.gap_advertise(adv_interval_us, adv_data=payload)
    
    try:
        while True:
            # 持續運行，可在此加入 LED 閃爍提示
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping BLE...")
        ble.gap_advertise(None)
        ble.active(False)

if __name__ == "__main__":
    main()
