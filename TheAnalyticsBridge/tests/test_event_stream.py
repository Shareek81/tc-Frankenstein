import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, time, timezone
from unittest.mock import Mock

from messaging.event_broadcaster import EventBroadcaster
from messaging.event_stream import EventStream
from messaging.exceptions import StreamClosed
from models import AttackLog, ProcessedEvent
from storage import EventStore


class EventStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = EventStore(capacity=2)
        self.broadcaster = EventBroadcaster(capacity=2)
        self.stream = EventStream(self.store, self.store, self.broadcaster, self.broadcaster)
        self.event = ProcessedEvent(
            "first", AttackLog(time(14, 30), "Brute Force", 8, "192.0.2.1"),
            80, "test", datetime.now(timezone.utc),
        )

    async def test_history_then_live_without_gap_or_duplicate(self):
        self.stream.append(self.event)
        with self.stream.connect() as connection:
            second = replace(self.event, event_id="second")
            self.stream.append(second)
            self.assertEqual(connection.history, (self.event,))
            self.assertEqual(await connection.subscription.receive(), second)
            self.assertEqual(self.store.snapshot(), (self.event, second))
        self.assertEqual(self.broadcaster.subscriber_count, 0)

    async def test_each_client_receives_every_new_event(self):
        with self.stream.connect() as first, self.stream.connect() as second:
            self.assertEqual(first.history, ())
            self.stream.append(self.event)
            self.assertEqual(await first.subscription.receive(), self.event)
            self.assertEqual(await second.subscription.receive(), self.event)

    async def test_slow_client_is_closed_without_blocking_healthy_client(self):
        with self.stream.connect() as slow, self.stream.connect() as fast:
            for index in range(3):
                event = replace(self.event, event_id=str(index))
                self.stream.append(event)
                self.assertEqual(await fast.subscription.receive(), event)
            with self.assertRaises(StreamClosed):
                await slow.subscription.receive()
            self.assertEqual(self.broadcaster.subscriber_count, 1)
        with self.stream.connect() as reconnect:
            self.assertEqual([event.event_id for event in reconnect.history], ["1", "2"])

    async def test_close_wakes_waiting_subscriber(self):
        with self.stream.connect() as connection:
            waiter = asyncio.create_task(connection.subscription.receive())
            self.broadcaster.close()
            with self.assertRaises(StreamClosed):
                await asyncio.wait_for(waiter, timeout=1)
        with self.assertRaises(StreamClosed):
            with self.stream.connect():
                pass

    async def test_store_failure_does_not_publish(self):
        writer = Mock()
        writer.append.side_effect = OSError("store unavailable")
        publisher = Mock()
        stream = EventStream(self.store, writer, publisher, self.broadcaster)
        with self.assertRaises(OSError):
            stream.append(self.event)
        publisher.publish.assert_not_called()

    async def test_snapshot_failure_cleans_subscription(self):
        reader = Mock()
        reader.snapshot.side_effect = OSError("read failed")
        stream = EventStream(reader, self.store, self.broadcaster, self.broadcaster)
        with self.assertRaises(OSError):
            with stream.connect():
                pass
        self.assertEqual(self.broadcaster.subscriber_count, 0)

if __name__ == "__main__":
    unittest.main()