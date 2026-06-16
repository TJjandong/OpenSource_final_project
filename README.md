# OpenSource_final_project
## 🛠️ 環境建置：Linux VM 藍牙網卡韌體修復指南 (Realtek RTL8761B)

### 📌 問題描述
在虛擬機 (VM) 中透過 USB Passthrough 掛載藍牙接收器後，使用 `lsusb` 可看到硬體 (Realtek)，但 `hciconfig` 顯示狀態為 `DOWN`，且 MAC 位址為全零 (`00:00:00:00:00:00`)。
經由 `dmesg | grep -i blue` 查明原因為 Linux 核心缺少 Realtek 專屬的韌體檔案 (`rtl8761b_fw.bin`)。

### 🚀 解決步驟

**1. 建立韌體存放資料夾**
```bash
sudo mkdir -p /lib/firmware/rtl_bt
```

**2. 從官方開源庫下載韌體與設定檔**
```bash
sudo wget [https://raw.githubusercontent.com/Realtek-OpenSource/android_hardware_realtek/rtk1395/bt/rtkbt/Firmware/BT/rtl8761b_fw](https://raw.githubusercontent.com/Realtek-OpenSource/android_hardware_realtek/rtk1395/bt/rtkbt/Firmware/BT/rtl8761b_fw) -O /lib/firmware/rtl_bt/rtl8761b_fw.bin
sudo wget [https://raw.githubusercontent.com/Realtek-OpenSource/android_hardware_realtek/rtk1395/bt/rtkbt/Firmware/BT/rtl8761b_config](https://raw.githubusercontent.com/Realtek-OpenSource/android_hardware_realtek/rtk1395/bt/rtkbt/Firmware/BT/rtl8761b_config) -O /lib/firmware/rtl_bt/rtl8761b_config.bin
```
**3.重新載入硬體與服務**
```bash
sudo systemctl restart bluetooth
sudo hciconfig hci0 up
```
