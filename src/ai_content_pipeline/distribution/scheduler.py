"""发布调度：支持 Redis ZSET 延时队列与进程内队列（demo）。"""

from __future__ import annotations

import heapq
import json
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable

from ai_content_pipeline.models import PublishTask, PublishStatus


class PublishScheduler(ABC):
    @abstractmethod
    def schedule(self, task: PublishTask) -> None:
        """将任务写入延时队列。"""

    @abstractmethod
    def poll_due(self, now: datetime | None = None) -> list[PublishTask]:
        """取出已到期的任务（不移除，由 publisher ack 后移除）。"""

    @abstractmethod
    def ack(self, task_id: str) -> None:
        """确认任务已处理。"""


class InMemoryScheduler(PublishScheduler):
    """进程内最小堆实现：demo / 测试 / 单机部署。"""

    def __init__(self, on_due: Callable[[PublishTask], None] | None = None) -> None:
        self._heap: list[tuple[float, int, PublishTask]] = []
        self._seq = 0
        self._pending: dict[str, PublishTask] = {}
        self._lock = threading.RLock()
        self.on_due = on_due

    def schedule(self, task: PublishTask) -> None:
        with self._lock:
            self._seq += 1
            ts = task.publish_at.timestamp()
            heapq.heappush(self._heap, (ts, self._seq, task))
            self._pending[task.task_id] = task

    def poll_due(self, now: datetime | None = None) -> list[PublishTask]:
        now_ts = (now or datetime.now(timezone.utc)).timestamp()
        due: list[PublishTask] = []
        with self._lock:
            while self._heap and self._heap[0][0] <= now_ts:
                _, _, task = heapq.heappop(self._heap)
                if task.task_id in self._pending:
                    due.append(task)
        if self.on_due:
            for task in due:
                self.on_due(task)
        return due

    def ack(self, task_id: str) -> None:
        with self._lock:
            self._pending.pop(task_id, None)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)


class RedisZSetScheduler(PublishScheduler):
    """Redis ZSET 延时队列：生产环境多实例共享。"""

    KEY = "publish_queue"

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        try:
            import redis as redis_lib
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("缺少 redis，请安装可选依赖: pip install -e '.[worker]'") from exc
        self._redis = redis_lib.Redis.from_url(redis_url, decode_responses=True)

    def schedule(self, task: PublishTask) -> None:
        self._redis.zadd(self.KEY, {json.dumps(task.model_dump(), ensure_ascii=False): task.publish_at.timestamp()})

    def poll_due(self, now: datetime | None = None) -> list[PublishTask]:
        now_ts = (now or datetime.now(timezone.utc)).timestamp()
        raw_tasks = self._redis.zrangebyscore(self.KEY, 0, now_ts, start=0, num=100)
        return [PublishTask.model_validate(json.loads(raw)) for raw in raw_tasks]

    def ack(self, task_id: str) -> None:
        for raw in self._redis.zrange(self.KEY, 0, -1):
            task = json.loads(raw)
            if task["task_id"] == task_id:
                self._redis.zrem(self.KEY, raw)
                return

