from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .config import TrackerSettings
from .models import SignalReading
from .processing import ExponentialSmoother, SignalHistory, clamp, estimate_distance
from .sources import BleSignalSource, IoctlSignalSource, SignalSource, SimulatedSignalSource


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
        try:
            rssi = self.source.read()
            self.last_status = f"{self.mode} mode"
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
        )


class SignalDashboard(tk.Tk):
    def __init__(self, controller: TrackerController) -> None:
        super().__init__()
        self.controller = controller
        self.title("Indoor Tracker Demo")
        self.geometry("920x560")
        self.minsize(860, 520)

        self.configure(bg="#111827")
        self._build_styles()
        self._build_layout()
        self.after(self.controller.settings.update_interval_ms, self._tick)

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Card.TFrame", background="#1f2937")
        style.configure("Headline.TLabel", background="#111827", foreground="#f9fafb", font=("Segoe UI", 22, "bold"))
        style.configure("Subhead.TLabel", background="#111827", foreground="#9ca3af", font=("Segoe UI", 10))
        style.configure("Metric.TLabel", background="#1f2937", foreground="#f9fafb", font=("Segoe UI", 20, "bold"))
        style.configure("Caption.TLabel", background="#1f2937", foreground="#cbd5e1", font=("Segoe UI", 10))
        style.configure("Value.TLabel", background="#1f2937", foreground="#7dd3fc", font=("Segoe UI", 30, "bold"))
        style.configure("Status.TLabel", background="#111827", foreground="#fbbf24", font=("Segoe UI", 10, "bold"))

    def _build_layout(self) -> None:
        header = ttk.Frame(self, style="Card.TFrame")
        header.pack(fill="x", padx=20, pady=(20, 12))
        title = ttk.Label(header, text="室內定位追蹤原型", style="Headline.TLabel")
        title.pack(anchor="w", padx=18, pady=(18, 4))
        subtitle = ttk.Label(
            header,
            text="模擬模式可直接 demo；live 模式會嘗試從實際藍牙廣播讀取 RSSI。",
            style="Subhead.TLabel",
        )
        subtitle.pack(anchor="w", padx=18, pady=(0, 16))

        body = ttk.Frame(self, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        self.status_var = tk.StringVar(value=self.controller.last_status)
        self.rssi_var = tk.StringVar(value="-- dBm")
        self.smoothed_var = tk.StringVar(value="-- dBm")
        self.distance_var = tk.StringVar(value="-- m")
        self.time_var = tk.StringVar(value="--")

        left = ttk.Frame(body, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 10), pady=16)
        right = ttk.Frame(body, style="Card.TFrame")
        right.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(10, 16), pady=16)

        self._metric_card(left, "即時 RSSI", self.rssi_var, 0)
        self._metric_card(left, "平滑 RSSI", self.smoothed_var, 1)
        self._metric_card(left, "估算距離", self.distance_var, 2)
        self._metric_card(left, "最後更新", self.time_var, 3)

        status = ttk.Label(left, textvariable=self.status_var, style="Status.TLabel")
        status.grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 16))

        self.bar_canvas = tk.Canvas(left, height=62, bg="#0f172a", highlightthickness=0)
        self.bar_canvas.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))
        self.bar_canvas.bind("<Configure>", lambda _event: self._draw_signal_bar())

        trend_title = ttk.Label(right, text="RSSI 趨勢", style="Metric.TLabel")
        trend_title.pack(anchor="w", padx=16, pady=(16, 8))
        self.chart = tk.Canvas(right, bg="#0f172a", highlightthickness=0)
        self.chart.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.chart.bind("<Configure>", lambda _event: self._draw_chart())

    def _metric_card(self, parent: ttk.Frame, title: str, variable: tk.StringVar, row: int) -> None:
        label = ttk.Label(parent, text=title, style="Caption.TLabel")
        label.grid(row=row * 2, column=0, sticky="w", padx=16, pady=(14 if row == 0 else 8, 0))
        value = ttk.Label(parent, textvariable=variable, style="Value.TLabel")
        value.grid(row=row * 2 + 1, column=0, sticky="w", padx=16, pady=(0, 4))

    def _tick(self) -> None:
        reading = self.controller.next_reading()
        self.status_var.set(reading.source)
        self.rssi_var.set(f"{reading.rssi} dBm")
        self.smoothed_var.set(f"{reading.smoothed_rssi:.1f} dBm")
        self.distance_var.set(f"{reading.estimated_distance_m:.2f} m")
        self.time_var.set(reading.timestamp.strftime("%H:%M:%S"))
        self._draw_signal_bar()
        self._draw_chart()
        self.after(self.controller.settings.update_interval_ms, self._tick)

    def _draw_signal_bar(self) -> None:
        canvas = self.bar_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        latest = self.controller.history.latest() or -90.0
        normalized = clamp((latest + 95.0) / 60.0, 0.0, 1.0)
        fill_width = int(width * normalized)
        canvas.create_rectangle(0, 0, width, height, fill="#111827", outline="")
        canvas.create_rectangle(0, 0, fill_width, height, fill="#22c55e", outline="")
        canvas.create_text(14, height // 2, anchor="w", fill="#e5e7eb", font=("Segoe UI", 11, "bold"), text="訊號強度")

    def _draw_chart(self) -> None:
        canvas = self.chart
        canvas.delete("all")
        values = self.controller.history.values()
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.create_rectangle(0, 0, width, height, fill="#0f172a", outline="")
        if len(values) < 2:
            canvas.create_text(width // 2, height // 2, fill="#64748b", text="等待 RSSI 資料...", font=("Segoe UI", 12))
            return

        min_rssi = -95.0
        max_rssi = -35.0
        points = []
        step = width / max(len(values) - 1, 1)
        for index, value in enumerate(values):
            x = index * step
            y_ratio = (value - min_rssi) / (max_rssi - min_rssi)
            y_ratio = clamp(y_ratio, 0.0, 1.0)
            y = height - (y_ratio * (height - 32)) - 16
            points.extend([x, y])

        canvas.create_line(*points, fill="#38bdf8", width=3, smooth=True)
        for mark in (-90, -75, -60, -45):
            y_ratio = (mark - min_rssi) / (max_rssi - min_rssi)
            y = height - (y_ratio * (height - 32)) - 16
            canvas.create_line(0, y, width, y, fill="#1f2937")
            canvas.create_text(10, y, anchor="w", fill="#64748b", text=f"{mark} dBm", font=("Segoe UI", 9))


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Indoor tracker demo")
    parser.add_argument("--mode", choices=("sim", "live", "lkm"), default="sim", help="signal source mode")
    return parser


def main() -> None:
    args = build_argument_parser().parse_args()
    settings = TrackerSettings()
    controller = TrackerController(settings, args.mode)
    app = SignalDashboard(controller)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
