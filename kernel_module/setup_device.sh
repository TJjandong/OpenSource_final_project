#!/bin/bash
# setup_device.sh — 一鍵設定 pico_tracker 核心模組與裝置節點
#
# 使用方式：
#   sudo bash kernel_module/setup_device.sh [target_name] [hci_dev_id]
#
# 參數（皆可選）：
#   target_name  目標 BLE 裝置名稱（預設：Pico-Tracker）
#   hci_dev_id   HCI 裝置索引（預設：0，對應 hci0）
#
# 範例：
#   sudo bash kernel_module/setup_device.sh
#   sudo bash kernel_module/setup_device.sh "Pico-Tracker" 0

set -euo pipefail

TARGET_NAME="${1:-Pico-Tracker}"
HCI_DEV_ID="${2:-0}"
MODULE_DIR="$(dirname "$0")"
DEVICE_NAME="pico_tracker"

echo "=== PicoTracker Kernel Module Setup ==="
echo "  Target BLE Name : ${TARGET_NAME}"
echo "  HCI device      : hci${HCI_DEV_ID}"
echo ""

# ── 1. 確認以 root 執行 ──
if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] This script must be run as root (sudo)." >&2
    exit 1
fi

# ── 2. 停止 bluetoothd（HCI_CHANNEL_RAW 需獨占 HCI 裝置）──
echo "[1/5] Stopping bluetooth service..."
if systemctl is-active --quiet bluetooth; then
    systemctl stop bluetooth
    echo "      ✓ bluetoothd stopped."
else
    echo "      ✓ bluetoothd was not running."
fi

# ── 3. 若模組已載入，先卸載（釋放裝置佔用） ──
if lsmod | grep -q "^${DEVICE_NAME}"; then
    echo "[2/5] Unloading existing module..."
    if ! rmmod "${DEVICE_NAME}" 2>/dev/null; then
        echo "[WARNING] Could not remove existing module '${DEVICE_NAME}'."
        echo "          It is likely in use by your Python GUI. Please close the GUI if insmod fails."
    fi
    sleep 1
fi

# ── 4. 確認 hci 裝置存在，並將介面帶 UP ──
echo "[3/5] Checking hci${HCI_DEV_ID}..."

# rfkill unblock 確保 radio 不被鎖定
rfkill unblock bluetooth 2>/dev/null || true
sleep 0.3

if ! hciconfig "hci${HCI_DEV_ID}" &>/dev/null; then
    echo "[ERROR] hci${HCI_DEV_ID} not found."
    echo "        Make sure Bluetooth adapter is connected and USB passthrough is enabled."
    echo "        Run: hciconfig -a"
    exit 1
fi

# 使用 RAW mode 必須確保硬體是 UP 狀態
# === 請把原本的 up 改成 down ===
echo "      Ensuring hci${HCI_DEV_ID} is DOWN (required for HCI_CHANNEL_USER)..."
hciconfig "hci${HCI_DEV_ID}" down 2>/dev/null || true
sleep 1
echo "      ✓ hci${HCI_DEV_ID} is DOWN."

# ── 5. 編譯並載入模組 ──
echo "[4/5] Building kernel module..."
make -C "${MODULE_DIR}" clean 2>/dev/null || true
make -C "${MODULE_DIR}"
echo "      ✓ Build successful."

echo "[5/5] Loading kernel module..."
# 在 VMware/VirtualBox 的 Shared Folder 中，直接 insmod 剛編譯出的 .ko
# 常會因為 Host OS (Windows) 的防毒軟體或 IDE 掃描鎖定檔案，導致 Device or resource busy。
# 解法：將 .ko 複製到原生的 /tmp 目錄後再載入。
TMP_KO="/tmp/${DEVICE_NAME}.ko"
cp "${MODULE_DIR}/pico_tracker.ko" "${TMP_KO}"

insmod "${TMP_KO}" \
    target_name="${TARGET_NAME}" \
    hci_dev_id="${HCI_DEV_ID}"

echo "      ✓ Module loaded."

# ── 5. 建立裝置節點 ──
echo "[5/5] Creating device node /dev/${DEVICE_NAME}..."

# 從 dmesg 取得 major number（模組 init 時已 printk）
sleep 0.5  # 等 dmesg 更新
MAJOR=$(dmesg | grep "PicoTracker: char device registered" | tail -1 | grep -oP 'major=\K[0-9]+')

if [[ -z "${MAJOR}" ]]; then
    echo "[ERROR] Could not determine major number from dmesg."
    echo "        Run: dmesg | grep PicoTracker"
    exit 1
fi

# 若裝置節點已存在，先移除
[[ -e "/dev/${DEVICE_NAME}" ]] && rm "/dev/${DEVICE_NAME}"

mknod "/dev/${DEVICE_NAME}" c "${MAJOR}" 0
chmod 666 "/dev/${DEVICE_NAME}"
echo "      ✓ /dev/${DEVICE_NAME} created (major=${MAJOR}, mode=666)"

# ── 完成 ──
echo ""
echo "=== Setup complete! ==="
echo ""
echo "Check kernel log:"
echo "  dmesg | grep PicoTracker"
echo ""
echo "Run the GUI (lkm mode, no Python BLE thread needed):"
echo "  python main.py --mode lkm"
echo ""
echo "To unload the module:"
echo "  sudo rmmod pico_tracker"
echo "  sudo systemctl start bluetooth  # restart bluetoothd if needed"
