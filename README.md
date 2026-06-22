# OpenSource_final_project — 室內定位追蹤原型

這個專案展示了一個完整的室內定位系統，具備三種運作模式：

1. **模擬模式**：不需要任何硬體，直接展示 RSSI 平滑、距離估算與即時視覺化。
2. **藍牙模式（live）**：透過 `bleak` 讀取真實 BLE 廣播資料（User Space 掃描）。
3. **核心模組模式（lkm）**：Linux Kernel Module 在核心空間直接控制藍牙介面，掃描並接收 Pico 2W 的廣播，不依賴任何 User Space BLE 工具。

## 執行方式

```bash
# 模擬模式（無需硬體）
python main.py

# LKM 模式（需先載入核心模組，詳見下方）
python main.py --mode lkm
```

## LKM 模式設定（推薦）

### 系統架構

```
Pico 2W（BLE 廣播，裝置名稱："PicoTracker"）
    ↓ HCI LE Advertising Report (event 0x3E, subevent 0x02)
Linux Kernel Module — ble_scan_thread_fn() kthread
    ├── 建立 AF_BLUETOOTH RAW socket (HCI_CHANNEL_RAW)
    ├── 送出 LE Set Scan Parameters / Enable 指令
    ├── 解析 HCI 事件，比對裝置名稱，提取 RSSI
    └── 推入環形緩衝區
         ↓ ioctl(PICO_GET_RSSI)
Python GUI（Tkinter）— 完全不變
```

**重點**：BLE 掃描、RSSI 讀取、斷線偵測全部在核心空間完成，Python 僅負責顯示。

### 快速啟動

在 **Linux** 環境（實機或 VM + USB Bluetooth Passthrough）：

```bash
# 1. 一鍵設定（停止 bluetoothd、編譯、載入模組、建立裝置節點）
sudo bash kernel_module/setup_device.sh

# 2. 啟動 GUI
python main.py --mode lkm
```

### 手動步驟

```bash
# 停止 bluetoothd（HCI_CHANNEL_RAW 需獨占 HCI 裝置）
sudo systemctl stop bluetooth

# 編譯
cd kernel_module
make

# 載入（可指定目標裝置名稱）
sudo insmod pico_tracker.ko target_name="PicoTracker" hci_dev_id=0

# 建立裝置節點
MAJOR=$(dmesg | grep "PicoTracker: char device registered" | tail -1 | grep -oP 'major=\K[0-9]+')
sudo mknod /dev/pico_tracker c $MAJOR 0
sudo chmod 666 /dev/pico_tracker

# 確認運作（應看到 BLE scan started）
dmesg | grep PicoTracker

# 啟動 GUI
python main.py --mode lkm

# 卸載
sudo rmmod pico_tracker
```

### 模組參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `target_name` | `PicoTracker` | 目標 BLE 裝置廣播名稱 |
| `hci_dev_id` | `0` | HCI 裝置索引（0 = hci0） |
| `disconnect_timeout_sec` | `15` | 幾秒未見目標後觸發斷線哨兵 |

### VM 注意事項

在 VirtualBox / VMware 中使用 USB 藍牙：
1. 關閉 Windows 側的藍牙（避免 USB 衝突）
2. 在 VM 設定中加入 USB Filter，將藍牙 USB dongle passthrough 給 VM
3. 在 VM 中確認：`hciconfig hci0` 可看到藍牙裝置

## 專案結構

```
.
├── main.py                    # 程式入口
├── kernel_module/
│   ├── pico_tracker.c         # LKM 主程式（含 HCI kthread、ring buffer、ioctl）
│   ├── pico_tracker.h         # ioctl 定義與哨兵常數
│   ├── Makefile               # 編譯腳本
│   └── setup_device.sh        # 一鍵設定腳本
├── indoor_tracker/
│   ├── app.py                 # Tkinter GUI（lkm 模式下不啟動任何 BLE thread）
│   ├── sources.py             # 訊號來源（IoctlSignalSource 透過 ioctl 讀 RSSI）
│   ├── processing.py          # RSSI 平滑與距離估算
│   ├── models.py              # 資料模型
│   └── config.py              # 設定
└── pico/                      # Pico 2W 韌體（BLE 廣播）
```

## 核心模組技術細節

`pico_tracker.c` 的 `ble_scan_thread_fn()` kthread 執行流程：

1. `sock_create_kern()` — 建立核心空間 `AF_BLUETOOTH SOCK_RAW` socket
2. `kernel_bind()` — 綁定到 `hci0`（`HCI_CHANNEL_RAW`）
3. `hci_send_raw(HCI_OP_LE_SET_SCAN_PARAM)` — 設定被動掃描參數（100ms interval）
4. `hci_send_raw(HCI_OP_LE_SET_SCAN_ENABLE)` — 開啟 LE 掃描
5. `kernel_recvmsg()` 接收迴圈 — 解析 HCI LE Meta Event（0x3E / 0x02）
6. `ad_match_name()` — 在 AD structures 中比對目標裝置名稱
7. `push_rssi()` — 寫入環形緩衝區，供 ioctl 讀取
8. 斷線監控 — 超過 `disconnect_timeout_sec` 秒未見目標時推入哨兵值（-9999）
