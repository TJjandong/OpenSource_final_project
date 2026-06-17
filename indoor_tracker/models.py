from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SignalReading:
    timestamp: datetime
    source: str
    rssi: int
    smoothed_rssi: float
    estimated_distance_m: float
