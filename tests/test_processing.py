import unittest

from indoor_tracker.processing import ExponentialSmoother, SignalHistory, estimate_distance


class ProcessingTests(unittest.TestCase):
    def test_exponential_smoother_behaves_like_weighted_average(self) -> None:
        smoother = ExponentialSmoother(alpha=0.25)
        first = smoother.update(-60)
        second = smoother.update(-50)
        self.assertEqual(first, -60.0)
        self.assertAlmostEqual(second, -57.5)

    def test_distance_decreases_when_rssi_is_stronger(self) -> None:
        far = estimate_distance(-80)
        near = estimate_distance(-55)
        self.assertGreater(far, near)

    def test_signal_history_keeps_only_latest_values(self) -> None:
        history = SignalHistory(maxlen=3)
        for value in (-90, -80, -70, -60):
            history.append(value)
        self.assertEqual(history.values(), [-80.0, -70.0, -60.0])


if __name__ == "__main__":
    unittest.main()