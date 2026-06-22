import bluetooth
import time
import struct
import machine
import gc
from micropython import const  # 確保 const 可用

# ── 常數定義 ──
_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID16_COMPLETE = const(0x03)

# 設備名稱 (必須與 Linux Kernel 端完全一致)
NAME = "Pico-Tracker"
UUID16 = 0xFEED
# 廣播間隔: 100ms (100,000 微秒)，達成 1 秒內極速斷線偵測的關鍵
ADV_INTERVAL_US = 100_000 

# 初始化板載 LED (Pico W 的 LED 連接在 'WL_GPIO0'，傳統 Pico 在 Pin 25)
# 如果你是用傳統 Pico (無 WiFi)，請改為 machine.Pin(25, machine.Pin.OUT)
try:
    led = machine.Pin("LED", machine.Pin.OUT)
except TypeError:
    led = machine.Pin(25, machine.Pin.OUT)

def build_advertising_payload(name, uuid16):
    """
    依照藍牙核心規範建構 Advertising Data
    格式: [Length] [AD Type] [AD Data]
    """
    payload = bytearray()
    
    # 1. Flags: LE General Discoverable | BR/EDR Not Supported
    payload.append(2)
    payload.append(_ADV_TYPE_FLAGS)
    payload.append(0x06) 
    
    # 2. Complete 16-bit UUID (Little-Endian)
    payload.append(3)
    payload.append(_ADV_TYPE_UUID16_COMPLETE)
    payload.extend(struct.pack("<H", uuid16))
    
    # 3. Complete Local Name
    name_bytes = name.encode("utf-8")
    payload.append(len(name_bytes) + 1)
    payload.append(_ADV_TYPE_NAME)
    payload.extend(name_bytes)
    
    # 安全檢查：BLE 廣播封包最大不能超過 31 bytes
    if len(payload) > 31:
        raise ValueError("Advertising payload exceeds 31 bytes!")
        
    return payload

def main():
    print("=== Pico Tracker BLE Beacon ===")
    print("Initializing BLE...")
    
    ble = bluetooth.BLE()
    ble.active(True)
    
    payload = build_advertising_payload(NAME, UUID16)
    
    print(f"Name: {NAME}")
    print(f"UUID: 0x{UUID16:04X}")
    print(f"Interval: {ADV_INTERVAL_US / 1000} ms")
    
    # 開始廣播 (Connectable = False，因為我們只是 Beacon)
    ble.gap_advertise(ADV_INTERVAL_US, adv_data=payload, connectable=False)
    print("Broadcasting...")
    
    led_state = False
    
    try:
        while True:
            # LED 呼吸閃爍，證明系統活著
            led_state = not led_state
            led.value(led_state)
            
            # 避免記憶體破碎
            gc.collect()
            
            # 迴圈休眠 0.5 秒 (不影響底層 BLE 晶片的廣播排程)
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\nStopping BLE...")
    finally:
        # 確保程式結束時關閉藍牙與 LED
        ble.gap_advertise(None)
        ble.active(False)
        led.value(0)
        print("Shutdown complete.")

if __name__ == "__main__":
    main()