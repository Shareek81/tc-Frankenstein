import asyncio
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, time, timezone
from unittest.mock import AsyncMock, Mock

from messaging.event_queue import EventQueue
from models import AttackLog, LegacyLog
from models.event_assessment import EventAssessment
from models.processed_event import ProcessedEvent
from processing.event_processor import EventProcessor
from storage import EventStore


def attack(severity=8):
    return AttackLog(time(14, 30), "Brute Force", severity, "103.25.12.45")


def legacy(status="Failed"):
    return LegacyLog(datetime(2026, 9, 12, 14, 30), "45.33.22.11", "SSH Connection", status)


class EventStoreTests(unittest.TestCase):
    def test_processed_assessment_requires_two_valid_points_in_each_group(self):
        base = ProcessedEvent("event", attack(), 80, "mock", datetime.now(timezone.utc))
        self.assertEqual(base.to_payload()["insight"], [])
        for points in (("one",), ("one", "two", "three"), (" ", "two"), (1, "two"), ("x" * 401, "two")):
            with self.subTest(points=points), self.assertRaises(ValueError):
                replace(base, insight=points, respondsuggested=("Check logs", "Verify account"))
        with self.assertRaises(ValueError):
            replace(base, insight=("one", "two"))

    def test_bounded_history_is_oldest_first_and_snapshots_are_detached(self):
        store = EventStore(capacity=2)
        self.assertEqual(store.snapshot(), ())
        first = ProcessedEvent("first", attack(), 80, "mock", datetime.now(timezone.utc))
        second = replace(first, event_id="second")
        third = replace(first, event_id="third")
        store.append(first)
        store.append(second)
        snapshot = store.snapshot()
        store.append(third)
        self.assertEqual(snapshot, (first, second))
        self.assertEqual(store.snapshot(), (second, third))
        with self.assertRaises(FrozenInstanceError):
            first.danger_score = 0

    def test_processed_score_must_be_an_integer_in_range(self):
        for score in (-1, 0, 101, True, 0.5, "80"):
            with self.subTest(score=score), self.assertRaises(ValueError):
                ProcessedEvent("event", attack(), score, "mock", datetime.now(timezone.utc))
        for score in (1, 100):
            self.assertEqual(
                ProcessedEvent("event", attack(), score, "mock", datetime.now(timezone.utc)).danger_score,
                score,
            )


class EventProcessorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assessment = EventAssessment(80, ("Observed activity", "Review context"), ("Check logs", "Verify account"))
        self.scorer = Mock(score=AsyncMock(return_value=self.assessment))
        self.scorer.name = "test"

    async def test_each_log_is_scored_stored_and_acknowledged(self):
        queue = EventQueue(capacity=2)
        store = EventStore(capacity=10)
        self.scorer.score.side_effect = [self.assessment, replace(self.assessment, danger_score=60)]
        processor = EventProcessor(queue, self.scorer, store)
        logs = (attack(), legacy())
        for log in logs:
            await queue.put(log)
        before = datetime.now(timezone.utc)
        first = await processor.process_once()
        second = await processor.process_once()
        self.assertEqual(store.snapshot(), (first, second))
        self.assertEqual((first.log, second.log), logs)
        self.assertEqual((first.danger_score, second.danger_score), (80, 60))
        self.assertEqual(first.insight, self.assessment.insight)
        self.assertEqual(first.respondsuggested, self.assessment.respondsuggested)
        self.assertEqual(first.to_payload()["insight"], list(self.assessment.insight))
        self.assertEqual(first.to_payload()["respondsuggested"], list(self.assessment.respondsuggested))
        self.assertNotEqual(first.event_id, second.event_id)
        self.assertEqual(first.scoring_method, "test")
        self.assertLessEqual(before, first.processed_at)
        self.assertEqual(first.processed_at.tzinfo, timezone.utc)
        self.assertEqual(first.log.time, time(14, 30))
        await asyncio.wait_for(queue.join(), timeout=1)
        self.assertEqual(queue.qsize(), 0)

    async def test_scoring_failure_retains_unscored_event_and_continues_without_retry(self):
        queue = EventQueue(capacity=2)
        store = EventStore(capacity=2)
        first_log, second_log = attack(), legacy()
        await queue.put(first_log)
        await queue.put(second_log)
        self.scorer.score.side_effect = [RuntimeError("provider failed"), self.assessment]
        task = asyncio.create_task(EventProcessor(queue, self.scorer, store).run())
        try:
            await asyncio.wait_for(queue.join(), timeout=1)
            first, second = store.snapshot()
            self.assertIsNone(first.danger_score)
            self.assertEqual(first.scoring_method, "unavailable")
            self.assertEqual(first.insight, ())
            self.assertEqual(first.respondsuggested, ())
            self.assertIsNone(first.to_payload()["danger_score"])
            self.assertEqual(second.danger_score, 80)
            self.assertEqual(self.scorer.score.await_count, 2)
            self.assertEqual([call.args[0] for call in self.scorer.score.await_args_list], [first_log, second_log])
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_invalid_internal_assessment_still_propagates(self):
        source = Mock(get=AsyncMock(return_value=attack()))
        self.scorer.score.return_value = replace(self.assessment, danger_score=101)
        with self.assertRaises(ValueError):
            await EventProcessor(source, self.scorer, Mock()).process_once()

    def test_unscored_event_cannot_have_insights(self):
        with self.assertRaises(ValueError):
            ProcessedEvent("event", attack(), None, "unavailable", datetime.now(timezone.utc),
                           insight=("one", "two"), respondsuggested=("one", "two"))

    async def test_storage_failure_propagates_and_balances_queue_accounting(self):
        queue = EventQueue(capacity=1)
        await queue.put(attack())
        store = Mock()
        store.append.side_effect = RuntimeError("storage failed")
        with self.assertRaises(RuntimeError):
            await EventProcessor(queue, self.scorer, store).process_once()
        await asyncio.wait_for(queue.join(), timeout=1)

    async def test_run_drains_queue_and_cancels_while_idle(self):
        queue = EventQueue(capacity=2)
        store = EventStore(capacity=2)
        await queue.put(attack())
        await queue.put(legacy())
        task = asyncio.create_task(EventProcessor(queue, self.scorer, store).run())
        try:
            await asyncio.wait_for(queue.join(), timeout=1)
            self.assertEqual(len(store.snapshot()), 2)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_cancellation_during_scoring_balances_queue_accounting(self):
        queue = EventQueue(capacity=1)
        await queue.put(attack())
        started = asyncio.Event()

        async def score(log):
            started.set()
            await asyncio.Event().wait()

        scorer = Mock(score=score)
        scorer.name = "test"
        store = EventStore(capacity=1)
        task = asyncio.create_task(EventProcessor(queue, scorer, store).run())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(store.snapshot(), ())
        await asyncio.wait_for(queue.join(), timeout=1)


if __name__ == "__main__":
    unittest.main()