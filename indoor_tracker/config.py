from dataclasses import dataclass


@dataclass(frozen=True)
class TrackerSettings:
    target_uuid: str = "0000FEED-0000-1000-8000-00805F9B34FB"
    tx_power_dbm: float = -59.0
    path_loss_exponent: float = 2.2
    smoothing_alpha: float = 0.28
    history_size: int = 48
    update_interval_ms: int = 500
