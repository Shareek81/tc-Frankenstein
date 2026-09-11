import asyncio
import unittest
from datetime import datetime, time

from messaging.event_queue import EventQueue
from models import AttackLog, ILog, LegacyLog


class EventQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.attack = AttackLog(time(14, 30), "Brute Force", 8, "103.25.12.45")
        self.legacy = LegacyLog(
            datetime.fromisoformat("2026-09-11T14:30:00+05:30"),
            "45.33.22.11", "SSH Connection", "Failed",
        )

    async def test_both_event_types_are_delivered_in_arrival_order(self):
        self.assertIsInstance(self.attack, ILog)
        self.assertIsInstance(self.legacy, ILog)
        queue = EventQueue(capacity=2)
        await queue.put(self.attack)
        await queue.put(self.legacy)
        self.assertEqual(queue.qsize(), 2)
        self.assertIs(await queue.get(), self.attack)
        queue.task_done()
        self.assertIs(await queue.get(), self.legacy)
        queue.task_done()
        self.assertEqual(queue.qsize(), 0)
        await asyncio.wait_for(queue.join(), timeout=1)

    async def test_full_queue_pauses_producer_without_dropping_events(self):
        queue = EventQueue(capacity=1)
        await queue.put(self.attack)
        started = asyncio.Event()

        async def produce():
            started.set()
            await queue.put(self.legacy)

        producer = asyncio.create_task(produce())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertFalse(producer.done())
            self.assertIs(await queue.get(), self.attack)
            queue.task_done()
            await asyncio.wait_for(producer, timeout=1)
            self.assertIs(await queue.get(), self.legacy)
            queue.task_done()
        finally:
            if not producer.done():
                producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def test_join_waits_for_processing_not_just_get(self):
        queue = EventQueue(capacity=1)
        await queue.put(self.attack)
        await queue.get()
        started = asyncio.Event()

        async def wait_for_completion():
            started.set()
            await queue.join()

        waiter = asyncio.create_task(wait_for_completion())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertFalse(waiter.done())
            queue.task_done()
            await asyncio.wait_for(waiter, timeout=1)
        finally:
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    async def test_empty_queue_waits_and_allows_cancellation(self):
        queue = EventQueue(capacity=1)
        started = asyncio.Event()

        async def consume():
            started.set()
            return await queue.get()

        consumer = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertFalse(consumer.done())
        finally:
            consumer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await consumer
        await queue.put(self.attack)
        self.assertIs(await queue.get(), self.attack)
        queue.task_done()

    async def test_capacity_must_be_a_positive_integer(self):
        for capacity in (0, -1, True, 1.5, "2", None):
            with self.subTest(capacity=capacity):
                with self.assertRaises(ValueError):
                    EventQueue(capacity=capacity)

    async def test_contract_requires_from_json_implementation(self):
        class IncompleteLog(ILog):
            pass

        with self.assertRaises(TypeError):
            ILog()
        with self.assertRaises(TypeError):
            IncompleteLog()

    async def test_queue_accepts_another_log_implementation(self):
        class AdditionalLog(ILog):
            def to_payload(self) -> dict[str, object]:
                return {"event": "custom"}

            @classmethod
            def from_json(cls, payload: object) -> "AdditionalLog":
                return cls()

        event = AdditionalLog.from_json({})
        queue = EventQueue(capacity=1)
        await queue.put(event)
        self.assertIs(await queue.get(), event)
        queue.task_done()
        await asyncio.wait_for(queue.join(), timeout=1)


    async def test_contract_requires_serialization_implementation(self):
        class MissingSerialization(ILog):
            @classmethod
            def from_json(cls, payload):
                return cls()

        with self.assertRaises(TypeError):
            MissingSerialization()

    async def test_log_payloads_preserve_source_fields_and_round_trip(self):
        import json

        for log in (self.attack, self.legacy):
            with self.subTest(log_type=type(log).__name__):
                payload = json.loads(json.dumps(log.to_payload()))
                self.assertEqual(type(log).from_json(payload), log)
        self.assertEqual(self.attack.to_payload()["time"], "14:30:00")
        self.assertEqual(self.legacy.to_payload()["timestamp"], "2026-09-11T14:30:00+05:30")


if __name__ == "__main__":
    unittest.main()