"""进程内指标采集：生成耗时、发布成功率、错误数等。"""

from __future__ import annotations

import threading
import time
from functools import lru_cache


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.generation_count = 0
        self.generation_seconds_total = 0.0
        self.publish_success = 0
        self.publish_failed = 0
        self.error_count = 0
        self.started_at = time.time()

    def record_generation(self, seconds: float) -> None:
        with self._lock:
            self.generation_count += 1
            self.generation_seconds_total += seconds

    def record_publish(self, success: bool) -> None:
        with self._lock:
            if success:
                self.publish_success += 1
            else:
                self.publish_failed += 1

    def record_error(self) -> None:
        with self._lock:
            self.error_count += 1

    def snapshot(self) -> dict:
        with self._lock:
            published = self.publish_success + self.publish_failed
            return {
                "uptime_seconds": round(time.time() - self.started_at, 2),
                "generation_count": self.generation_count,
                "avg_generation_seconds": (
                    round(self.generation_seconds_total / self.generation_count, 3)
                    if self.generation_count
                    else 0.0
                ),
                "publish_success": self.publish_success,
                "publish_failed": self.publish_failed,
                "publish_success_rate": round(self.publish_success / published, 4) if published else 1.0,
                "error_count": self.error_count,
            }


@lru_cache
def get_metrics() -> Metrics:
    return Metrics()

