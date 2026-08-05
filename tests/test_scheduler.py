import unittest
from datetime import datetime, timedelta, timezone

from ai_content_pipeline.distribution.scheduler import InMemoryScheduler
from ai_content_pipeline.models import PublishTask


class InMemorySchedulerTests(unittest.TestCase):
    def test_schedule_and_poll_due(self):
        scheduler = InMemoryScheduler()
        now = datetime.now(timezone.utc)
        task = PublishTask(content_id="c1", platform="mock", publish_at=now - timedelta(seconds=1))
        scheduler.schedule(task)
        due = scheduler.poll_due()
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].task_id, task.task_id)
        scheduler.ack(task.task_id)
        self.assertEqual(scheduler.pending_count(), 0)

    def test_future_task_not_due(self):
        scheduler = InMemoryScheduler()
        now = datetime.now(timezone.utc)
        task = PublishTask(content_id="c1", platform="mock", publish_at=now + timedelta(hours=1))
        scheduler.schedule(task)
        self.assertEqual(scheduler.poll_due(), [])


if __name__ == "__main__":
    unittest.main()

