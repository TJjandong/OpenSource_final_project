# OpenSource_final_project

這個專案已整理成一個可執行的室內定位追蹤原型，主打兩個模式：

1. 模擬模式：不需要任何硬體，就能展示 RSSI 平滑、距離估算與即時視覺化。
2. 藍牙模式：若電腦上有安裝 `bleak` 且有可用藍牙掃描器，就能嘗試讀取實際廣播資料。

目前的實作重點是把提案中的應用層原型先做完整，讓專題能直接展示與測試；硬體層的 Pico 2 W 廣播與 Linux Kernel Module 可以之後再接上。

## 執行方式

```bash
python main.py
```

如果想嘗試實際掃描模式：

```bash
pip install bleak
python main.py --mode live
```

若 live 模式不可用，程式會自動退回模擬模式，避免整個專案卡住。

## 專案內容

- RSSI 平滑與距離估算模型
- 可視化儀表板，顯示當前 RSSI、估算距離與訊號趨勢
- 模擬訊號來源，方便沒硬體時直接 demo
- 可選的 BLE 掃描來源
- 單元測試，驗證平滑與距離換算邏輯

## 專案結構

- `main.py`：程式入口
- `indoor_tracker/processing.py`：RSSI 平滑、距離估算與歷史資料結構
- `indoor_tracker/sources.py`：模擬與 BLE 訊號來源
- `indoor_tracker/app.py`：Tkinter 即時介面
- `tests/test_processing.py`：核心邏輯測試

## 與原提案的對應

這版完成的是使用者空間的「定位雷達」與資料處理主線，已經能展示近距離冷熱變化與相對距離感知。提案中提到的 Kernel Module / ioctl / Pico 韌體，可以當成下一階段延伸；在課堂展示或 demo 場景中，這個版本已足夠獨立運作。
