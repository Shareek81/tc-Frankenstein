import asyncio
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, time, timezone
from unittest.mock import AsyncMock, Mock

from messaging.event_queue import EventQueue
from models import AttackLog, LegacyLog
from models.processed_event import ProcessedEvent
from processing.event_processor import EventProcessor
from storage import EventStore


def attack(severity=8):
    return AttackLog(time(14, 30), "Brute Force", severity, "103.25.12.45")


def legacy(status="Failed"):
    return LegacyLog(datetime(2026, 9, 12, 14, 30), "45.33.22.11", "SSH Connection", status)


class EventStoreTests(unittest.TestCase):
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

    def test_capacity_must_be_a_positive_integer(self):
        for capacity in (0, -1, True, 1.5, "2", None):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                EventStore(capacity=capacity)

    def test_processed_score_must_be_an_integer_in_range(self):
        for score in (-1, 0, 101, True, 0.5, "80", None):
            with self.subTest(score=score), self.assertRaises(ValueError):
                ProcessedEvent("event", attack(), score, "mock", datetime.now(timezone.utc))
        for score in (1, 100):
            self.assertEqual(
                ProcessedEvent("event", attack(), score, "mock", datetime.now(timezone.utc)).danger_score,
                score,
            )


class EventProcessorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scorer = Mock(score=AsyncMock(return_value=80))
        self.scorer.name = "test"

    async def test_each_log_is_scored_stored_and_acknowledged(self):
        queue = EventQueue(capacity=2)
        store = EventStore(capacity=10)
        self.scorer.score.side_effect = [80, 60]
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
        self.assertNotEqual(first.event_id, second.event_id)
        self.assertEqual(first.scoring_method, "test")
        self.assertLessEqual(before, first.processed_at)
        self.assertEqual(first.processed_at.tzinfo, timezone.utc)
        self.assertEqual(first.log.time, time(14, 30))
        await asyncio.wait_for(queue.join(), timeout=1)
        self.assertEqual(queue.qsize(), 0)

    async def test_dependencies_can_be_replaced_without_concrete_inheritance(self):
        source = Mock(get=AsyncMock(return_value=attack()))
        scorer = Mock(score=AsyncMock(return_value=42))
        scorer.name = "test"
        store = Mock()
        result = await EventProcessor(source, scorer, store).process_once()
        scorer.score.assert_awaited_once_with(result.log)
        store.append.assert_called_once_with(result)
        source.task_done.assert_called_once_with()
        self.assertEqual(result.danger_score, 42)
        self.assertEqual(result.scoring_method, "test")

    async def test_processing_failure_propagates_without_storing_an_event(self):
        for score, failure in ((80, RuntimeError("scoring failed")), (101, None)):
            with self.subTest(score=score):
                queue = EventQueue(capacity=1)
                await queue.put(attack())
                store = EventStore(capacity=1)
                scorer = Mock(score=AsyncMock(return_value=score, side_effect=failure))
                scorer.name = "test"
                with self.assertRaises(RuntimeError if failure else ValueError):
                    await EventProcessor(queue, scorer, store).run()
                self.assertEqual(store.snapshot(), ())
                await asyncio.wait_for(queue.join(), timeout=1)

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