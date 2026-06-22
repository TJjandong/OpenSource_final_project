from __future__ import annotations

import argparse
import math
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .config import TrackerSettings
from .models import SignalReading
from .processing import ExponentialSmoother, SignalHistory, clamp, estimate_distance
from .sources import BleSignalSource, IoctlSignalSource, SignalSource, SimulatedSignalSource, BeaconNotFoundError


class TrackerController:
    def __init__(self, settings: TrackerSettings, mode: str) -> None:
        self.settings = settings
        self.mode = mode
        self.smoother = ExponentialSmoother(settings.smoothing_alpha)
        self.history = SignalHistory(settings.history_size)
        self.source = self._create_source(mode)
        self.fallback_source = SimulatedSignalSource()
        self.last_status = "ready"

    def _create_source(self, mode: str) -> SignalSource:
        if mode == "lkm":
            return IoctlSignalSource()
        if mode == "live":
            return BleSignalSource(self.settings.target_uuid)
        return SimulatedSignalSource()

    def next_reading(self) -> SignalReading:
        connected = True
        try:
            rssi = self.source.read()
            self.last_status = f"{self.mode} mode"
        except BeaconNotFoundError:
            # Pico 斷線或找不到：重置 smoother，強制變為最遠狀態
            self.smoother.reset()
            rssi = -95
            connected = False
            self.last_status = "⚠️ Pico 未連線（距離過遠）"
        except Exception as exc:
            if self.mode == "live":
                self.source = self.fallback_source
                rssi = self.source.read()
                self.last_status = f"live unavailable, fallback to simulation: {exc}"
            else:
                raise

        smoothed = self.smoother.update(rssi)
        distance = estimate_distance(smoothed, self.settings.tx_power_dbm, self.settings.path_loss_exponent)
        self.history.append(smoothed)
        return SignalReading(
            timestamp=datetime.now(),
            source=self.last_status,
            rssi=rssi,
            smoothed_rssi=smoothed,
            estimated_distance_m=distance,
            connected=connected,
        )


# ─────────────────────────────────────────────────────────
# 斷線警報：紅色閃爍
# ─────────────────────────────────────────────────────────
_FLASH_COLOR    = "#7f1d1d"   # 閃爍時的背景紅色
_NORMAL_COLOR   = "#111827"   # 正常背景
_FLASH_CYCLES   = 3           # 閃幾次（每次 on/off 各 200 ms）
_FLASH_INTERVAL = 200         # ms


# 模式 → 顯示用標籤文字 / 徽章顏色
_MODE_LABEL = {
    "sim":  ("SIMULATION",    "#334155", "#94a3b8"),
    "live": ("BLE LIVE",      "#14532d", "#4ade80"),
    "lkm":  ("KERNEL MODULE", "#1e1b4b", "#818cf8"),
}


class SignalDashboard(tk.Tk):
    def __init__(self, controller: TrackerController) -> None:
        super().__init__()
        self.controller = controller
        self.title("PicoTrack — Kernel-Space BLE Indoor Positioning")
        self.geometry("1180x640")
        self.minsize(960, 560)

        self.configure(bg=_NORMAL_COLOR)
        self._flash_remaining = 0
        self._was_connected   = True

        self._build_styles()
        self._build_layout()
        self.after(self.controller.settings.update_interval_ms, self._tick)

    # ── 樣式 ──────────────────────────────────────────────
    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Card.TFrame",     background="#1f2937")
        style.configure("Header.TFrame",   background="#0d1117")
        style.configure("Headline.TLabel", background="#0d1117", foreground="#f9fafb",  font=("Segoe UI", 24, "bold"))
        style.configure("Logo.TLabel",     background="#0d1117", foreground="#818cf8",  font=("Segoe UI", 24, "bold"))
        style.configure("Subhead.TLabel",  background="#0d1117", foreground="#6b7280",  font=("Segoe UI", 10))
        style.configure("Metric.TLabel",   background="#1f2937", foreground="#f9fafb",  font=("Segoe UI", 20, "bold"))
        style.configure("Caption.TLabel",  background="#1f2937", foreground="#cbd5e1",  font=("Segoe UI", 10))
        style.configure("Value.TLabel",    background="#1f2937", foreground="#7dd3fc",  font=("Segoe UI", 28, "bold"))
        style.configure("Status.TLabel",   background="#111827", foreground="#fbbf24",  font=("Segoe UI", 10, "bold"))

    # ── 版面 ──────────────────────────────────────────────
    def _build_layout(self) -> None:
        mode = self.controller.mode
        mode_text, badge_bg, badge_fg = _MODE_LABEL.get(mode, (mode.upper(), "#374151", "#d1d5db"))

        # ── Header ──────────────────────────────────────────
        header = tk.Frame(self, bg="#0d1117")
        header.pack(fill="x", padx=20, pady=(20, 12))

        # 左側：品牌名稱
        brand_frame = tk.Frame(header, bg="#0d1117")
        brand_frame.pack(side="left", padx=18, pady=14)

        # 品牌 Logo 文字
        logo_line = tk.Frame(brand_frame, bg="#0d1117")
        logo_line.pack(anchor="w")
        tk.Label(logo_line, text="Pico",  bg="#0d1117", fg="#818cf8",
                 font=("Segoe UI", 26, "bold")).pack(side="left")
        tk.Label(logo_line, text="Track", bg="#0d1117", fg="#f9fafb",
                 font=("Segoe UI", 26, "bold")).pack(side="left")

        tk.Label(brand_frame,
                 text="Kernel-Space BLE Indoor Positioning System",
                 bg="#0d1117", fg="#6b7280",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        # 右側：模式徽章 + 系統資訊
        badge_frame = tk.Frame(header, bg="#0d1117")
        badge_frame.pack(side="right", padx=18, pady=14)

        # 模式徽章
        mode_badge = tk.Label(badge_frame, text=f"  {mode_text}  ",
                              bg=badge_bg, fg=badge_fg,
                              font=("Segoe UI", 10, "bold"),
                              padx=6, pady=3, relief="flat")
        mode_badge.pack(anchor="e")

        # 系統資訊行
        info_lines = [
            "Linux Kernel Module v3.7",
            "HCI Channel · User-Space ioctl",
            "BLE LE Scan · HCI_CHANNEL_USER",
        ]
        for line in info_lines:
            tk.Label(badge_frame, text=line,
                     bg="#0d1117", fg="#374151",
                     font=("Segoe UI", 8)).pack(anchor="e")

        # 分隔線
        tk.Frame(self, bg="#1f2937", height=1).pack(fill="x", padx=20)

        # --- Body（三欄）---
        body = ttk.Frame(self, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        body.columnconfigure(0, weight=2)   # metrics
        body.columnconfigure(1, weight=3)   # trend chart
        body.columnconfigure(2, weight=3)   # 2D map
        body.rowconfigure(0, weight=1)

        # StringVars
        self.status_var   = tk.StringVar(value=self.controller.last_status)
        self.rssi_var     = tk.StringVar(value="-- dBm")
        self.smoothed_var = tk.StringVar(value="-- dBm")
        self.distance_var = tk.StringVar(value="-- m")
        self.time_var     = tk.StringVar(value="--")

        # 左欄：指標卡片 + signal bar
        left = ttk.Frame(body, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 6), pady=16)

        self._metric_card(left, "即時 RSSI",  self.rssi_var,     0)
        self._metric_card(left, "平滑 RSSI",  self.smoothed_var, 1)
        self._metric_card(left, "估算距離",   self.distance_var, 2)
        self._metric_card(left, "最後更新",   self.time_var,     3)

        self.status_label = ttk.Label(left, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.grid(row=8, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 16))

        self.bar_canvas = tk.Canvas(left, height=62, bg="#0f172a", highlightthickness=0)
        self.bar_canvas.grid(row=9, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))
        self.bar_canvas.bind("<Configure>", lambda _: self._draw_signal_bar())

        # 中欄：RSSI 趨勢折線
        mid = ttk.Frame(body, style="Card.TFrame")
        mid.grid(row=0, column=1, sticky="nsew", padx=6, pady=16)
        ttk.Label(mid, text="RSSI 趨勢", style="Metric.TLabel").pack(anchor="w", padx=16, pady=(16, 8))
        self.chart = tk.Canvas(mid, bg="#0f172a", highlightthickness=0)
        self.chart.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.chart.bind("<Configure>", lambda _: self._draw_chart())

        # 右欄：2D 位置視覺化
        right = ttk.Frame(body, style="Card.TFrame")
        right.grid(row=0, column=2, sticky="nsew", padx=(6, 16), pady=16)
        ttk.Label(right, text="2D 位置估算", style="Metric.TLabel").pack(anchor="w", padx=16, pady=(16, 8))
        self.map_canvas = tk.Canvas(right, bg="#0a0f1a", highlightthickness=0)
        self.map_canvas.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.map_canvas.bind("<Configure>", lambda _: self._draw_2d_map())

        # 儲存最新 reading 供重繪用
        self._last_reading: SignalReading | None = None

    def _metric_card(self, parent: ttk.Frame, title: str, variable: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text=title, style="Caption.TLabel").grid(
            row=row * 2, column=0, sticky="w", padx=16, pady=(14 if row == 0 else 8, 0))
        ttk.Label(parent, textvariable=variable, style="Value.TLabel").grid(
            row=row * 2 + 1, column=0, sticky="w", padx=16, pady=(0, 4))

    # ── 主 tick ───────────────────────────────────────────
    def _tick(self) -> None:
        reading = self.controller.next_reading()
        self._last_reading = reading

        self.status_var.set(reading.source)
        self.rssi_var.set(f"{reading.rssi} dBm")
        self.smoothed_var.set(f"{reading.smoothed_rssi:.1f} dBm")
        self.distance_var.set(f"{reading.estimated_distance_m:.2f} m")
        self.time_var.set(reading.timestamp.strftime("%H:%M:%S"))

        # 剛斷線 → 觸發閃爍警報
        if not reading.connected and self._was_connected:
            self._trigger_disconnect_flash()
        self._was_connected = reading.connected

        self._draw_signal_bar()
        self._draw_chart()
        self._draw_2d_map()
        self.after(self.controller.settings.update_interval_ms, self._tick)

    # ── 斷線閃爍 ──────────────────────────────────────────
    def _trigger_disconnect_flash(self) -> None:
        """斷線瞬間觸發：背景紅色閃爍 N 次"""
        self._flash_remaining = _FLASH_CYCLES * 2   # on + off 各算一次
        self._do_flash()

    def _do_flash(self) -> None:
        if self._flash_remaining <= 0:
            self.configure(bg=_NORMAL_COLOR)
            return
        color = _FLASH_COLOR if (self._flash_remaining % 2 == 0) else _NORMAL_COLOR
        self.configure(bg=color)
        self._flash_remaining -= 1
        self.after(_FLASH_INTERVAL, self._do_flash)

    # ── 訊號強度 Bar ──────────────────────────────────────
    def _draw_signal_bar(self) -> None:
        canvas = self.bar_canvas
        canvas.delete("all")
        width  = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        latest = self.controller.history.latest() or -90.0
        normalized  = clamp((latest + 95.0) / 60.0, 0.0, 1.0)
        fill_width  = int(width * normalized)
        canvas.create_rectangle(0, 0, width, height, fill="#111827", outline="")
        canvas.create_rectangle(0, 0, fill_width, height, fill="#22c55e", outline="")
        canvas.create_text(14, height // 2, anchor="w", fill="#e5e7eb",
                           font=("Segoe UI", 11, "bold"), text="訊號強度")

    # ── RSSI 趨勢折線 ─────────────────────────────────────
    def _draw_chart(self) -> None:
        canvas = self.chart
        canvas.delete("all")
        values = self.controller.history.values()
        width  = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.create_rectangle(0, 0, width, height, fill="#0f172a", outline="")
        if len(values) < 2:
            canvas.create_text(width // 2, height // 2, fill="#64748b",
                               text="等待 RSSI 資料...", font=("Segoe UI", 12))
            return

        min_rssi, max_rssi = -95.0, -35.0
        points = []
        step = width / max(len(values) - 1, 1)
        for index, value in enumerate(values):
            x = index * step
            y_ratio = clamp((value - min_rssi) / (max_rssi - min_rssi), 0.0, 1.0)
            y = height - (y_ratio * (height - 32)) - 16
            points.extend([x, y])

        canvas.create_line(*points, fill="#38bdf8", width=3, smooth=True)
        for mark in (-90, -75, -60, -45):
            y_ratio = (mark - min_rssi) / (max_rssi - min_rssi)
            y = height - (y_ratio * (height - 32)) - 16
            canvas.create_line(0, y, width, y, fill="#1f2937")
            canvas.create_text(10, y, anchor="w", fill="#64748b",
                               text=f"{mark} dBm", font=("Segoe UI", 9))

    # ── 2D 位置視覺化 ─────────────────────────────────────
    def _draw_2d_map(self) -> None:
        canvas = self.map_canvas
        canvas.delete("all")

        w = max(canvas.winfo_width(),  1)
        h = max(canvas.winfo_height(), 1)
        cx, cy = w // 2, h // 2

        reading   = self._last_reading
        connected = (reading.connected if reading else True)
        distance  = (reading.estimated_distance_m if reading else 0.0)

        # ── 背景與格線 ────────────────────────────────────
        canvas.create_rectangle(0, 0, w, h, fill="#0a0f1a", outline="")
        for gx in range(0, w, 36):
            canvas.create_line(gx, 0, gx, h, fill="#0d1520")
        for gy in range(0, h, 36):
            canvas.create_line(0, gy, w, gy, fill="#0d1520")

        # ── 距離環（最大顯示 8 m）────────────────────────
        max_dist_m = 8.0
        max_radius = min(cx, cy) - 28
        scale      = max_radius / max_dist_m        # px / m

        ring_colors = {2: "#1e3a5f", 4: "#1e3a5f", 6: "#1e3a5f", 8: "#1e3a5f"}
        for ring_m, ring_color in ring_colors.items():
            r = int(ring_m * scale)
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               outline=ring_color, width=1)
            canvas.create_text(cx + r - 4, cy - 8, text=f"{ring_m}m",
                               fill="#334155", font=("Segoe UI", 8), anchor="e")

        # ── 訊號顏色（依距離）────────────────────────────
        if distance < 2.5:
            sig_color = "#22c55e"   # 綠：近
        elif distance < 5.0:
            sig_color = "#f59e0b"   # 黃：中
        else:
            sig_color = "#ef4444"   # 紅：遠

        # ── Pico beacon（中心點）─────────────────────────
        BR = 10  # beacon radius
        canvas.create_oval(cx - BR, cy - BR, cx + BR, cy + BR,
                           fill="#7c3aed", outline="#a78bfa", width=2)
        canvas.create_text(cx, cy + BR + 10, text="Pico 2W",
                           fill="#a78bfa", font=("Segoe UI", 9, "bold"))

        # ── 斷線狀態 ──────────────────────────────────────
        if not connected:
            # 半透明紅色覆蓋
            canvas.create_rectangle(0, 0, w, h, fill="#7f1d1d", stipple="gray50", outline="")
            canvas.create_text(cx, cy - 30,
                               text="⚠  DISCONNECTED",
                               fill="#fca5a5", font=("Segoe UI", 15, "bold"))
            canvas.create_text(cx, cy + 30,
                               text="Pico 訊號中斷",
                               fill="#fca5a5", font=("Segoe UI", 10))
            return

        # ── 距離圓（裝置可能位置的環）────────────────────
        dist_clamped = clamp(distance, 0.0, max_dist_m)
        radius = int(dist_clamped * scale)

        # 虛線距離環
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                           outline=sig_color, width=2, dash=(6, 4))

        # ── 裝置點（沿距離環緩慢公轉）────────────────────
        angle  = (time.time() * 0.4) % (2 * math.pi)   # 0.4 rad/s 慢速旋轉
        dx = cx + int(radius * math.cos(angle))
        dy = cy + int(radius * math.sin(angle))

        # 連線（beacon → 裝置）
        canvas.create_line(cx, cy, dx, dy, fill=sig_color, width=1, dash=(3, 4))

        # 裝置圓點（光暈 + 實心）
        GLOW = 14
        canvas.create_oval(dx - GLOW, dy - GLOW, dx + GLOW, dy + GLOW,
                           fill="", outline=sig_color, width=1)
        DR = 7
        canvas.create_oval(dx - DR, dy - DR, dx + DR, dy + DR,
                           fill=sig_color, outline="white", width=2)

        # 距離標籤（跟著裝置點）
        label_x = dx + (18 if dx < cx else -18)
        label_anchor = "w" if dx < cx else "e"
        canvas.create_text(label_x, dy - 14, anchor=label_anchor,
                           text=f"{distance:.2f} m",
                           fill=sig_color, font=("Segoe UI", 10, "bold"))

        # ── 訊號強度圖示（左下角）────────────────────────
        if reading:
            canvas.create_text(8, h - 8, anchor="sw",
                               text=f"RSSI {reading.rssi} dBm",
                               fill="#64748b", font=("Segoe UI", 9))


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Indoor tracker demo")
    parser.add_argument("--mode", choices=("sim", "live", "lkm"), default="sim",
                        help="signal source mode")
    return parser


def main() -> None:
    args = build_argument_parser().parse_args()
    settings = TrackerSettings()

    # LKM 模式：BLE 掃描由 kernel module 的 ble_scan_thread_fn() kthread 負責，
    # 不再需要 Python 啟動 bluetoothctl 或寫入 /dev/pico_tracker。
    # Python 只透過 IoctlSignalSource.read() → ioctl(PICO_GET_RSSI) 讀資料。
    controller = TrackerController(settings, args.mode)
    app = SignalDashboard(controller)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
