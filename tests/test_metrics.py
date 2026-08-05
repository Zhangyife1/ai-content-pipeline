import unittest

from ai_content_pipeline.observability.metrics import Metrics


class MetricsTests(unittest.TestCase):
    def test_snapshot(self):
        metrics = Metrics()
        metrics.record_generation(2.0)
        metrics.record_generation(4.0)
        metrics.record_publish(True)
        metrics.record_publish(False)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["generation_count"], 2)
        self.assertEqual(snapshot["avg_generation_seconds"], 3.0)
        self.assertEqual(snapshot["publish_success_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()

