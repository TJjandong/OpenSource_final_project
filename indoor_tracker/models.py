from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SignalReading:
    timestamp: datetime
    source: str
    rssi: int
    smoothed_rssi: float
    estimated_distance_m: float
    connected: bool = True          # False → Pico 斷線哨兵觸發
