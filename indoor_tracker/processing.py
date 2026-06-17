from collections import deque
import math


class ExponentialSmoother:
    def __init__(self, alpha: float) -> None:
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be between 0 and 1")
        self.alpha = alpha
        self._value = None

    def update(self, value: float) -> float:
        if self._value is None:
            self._value = float(value)
        else:
            self._value = self.alpha * float(value) + (1 - self.alpha) * self._value
        return self._value

    def reset(self) -> None:
        self._value = None


def estimate_distance(rssi: float, tx_power: float = -59.0, path_loss_exponent: float = 2.2) -> float:
    if path_loss_exponent <= 0:
        raise ValueError("path_loss_exponent must be positive")
    return 10 ** ((tx_power - float(rssi)) / (10 * path_loss_exponent))


class SignalHistory:
    def __init__(self, maxlen: int) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        self._values = deque(maxlen=maxlen)

    def append(self, value: float) -> None:
        self._values.append(float(value))

    def values(self) -> list[float]:
        return list(self._values)

    def latest(self) -> float | None:
        if not self._values:
            return None
        return self._values[-1]


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
