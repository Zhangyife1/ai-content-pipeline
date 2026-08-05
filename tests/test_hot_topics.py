import unittest

from ai_content_pipeline.ingestion.hot_topics import HotTopicAggregator, MockHotTopicSource


class HotTopicAggregatorTests(unittest.TestCase):
    def test_fetch_returns_ranked_topics(self):
        aggregator = HotTopicAggregator([MockHotTopicSource(), MockHotTopicSource()])
        topics = aggregator.fetch(limit=2)
        self.assertEqual(len(topics), 2)  # 同源去重
        self.assertEqual(topics[0].score, 98)
        self.assertEqual(topics[0].source, "mock")

    def test_topic_id_stable(self):
        source = MockHotTopicSource()
        a = source.fetch(limit=1)[0]
        b = source.fetch(limit=1)[0]
        self.assertEqual(a.topic_id, b.topic_id)


if __name__ == "__main__":
    unittest.main()

