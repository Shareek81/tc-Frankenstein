import asyncio
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from main import main
from messaging.event_queue import EventQueue
from messaging.event_broadcaster import EventBroadcaster
from models import AttackLog, LegacyLog
from storage import EventStore


class BridgeIngestionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.log_path = self.root / "live_stream.log"
        self.attack = {
            "time": "14:30:00", "type": "Brute Force",
            "severity": 8, "origin": "103.25.12.45",
        }
        self.legacy = {
            "timestamp": "2026-09-12T14:30:00+05:30", "source": "45.33.22.11",
            "event": "SSH Connection", "status": "Failed",
        }
        self.status = 200
        self.requested = asyncio.Event()

        async def respond_to_log(prompt, config=None, **kwargs):
            payload = json.loads(prompt.to_messages()[1].content.split("\n", 1)[1])
            log = payload["log"]
            score = log["severity"] * 10 if "severity" in log else 60
            return AIMessage(content=json.dumps({
                "danger_score": score,
                "insight": ["Observed event", "No confirmed compromise"],
                "respondsuggested": ["Review related logs", "Verify activity"],
            }))

        self.model = FakeListChatModel(responses=['{"danger_score": 80}'])
        self.model_invoke = self.enterContext(patch.object(
            FakeListChatModel, "ainvoke", new=AsyncMock(side_effect=respond_to_log),
        ))
        self.model_factory = self.enterContext(patch("integrations.llm.model_strategies.ChatGoogleGenerativeAI", return_value=self.model))
        self.local_model_factory = self.enterContext(patch("integrations.llm.model_strategies.ChatOllama", return_value=self.model))

        def respond(request):
            self.requested.set()
            return httpx.Response(self.status, json=[self.legacy])

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(self.client.aclose)
        self.queue = EventQueue(capacity=10)
        self.saved_events = asyncio.Queue()

        class ObservedStore(EventStore):
            def append(store, event):
                super().append(event)
                self.saved_events.put_nowait(event)

        self.store = ObservedStore(capacity=10)
        self.environment = {
            "EVENT_QUEUE_CAPACITY": "10",
            "EVENT_STORE_CAPACITY": "10",
            "SSE_QUEUE_CAPACITY": "10",
            "ATTACK_LOG_PATH": "live_stream.log",
            "ATTACK_WATCH_RETRY_SECONDS": "0.02",
            "LEGACYCORE_ENDPOINT": "http://localhost:5195/api/raw-logs",
            "LEGACY_POLL_INTERVAL_SECONDS": "0.02",
            "LEGACY_REQUEST_TIMEOUT_SECONDS": "1",
            "LEGACY_DEDUP_CAPACITY": "100",
            "LLM_MODEL": "test-model",
            "LLM_MODEL_TYPE": "gemini",
            "GOOGLE_API_KEY": "test-not-a-real-key",
        }

    def append_attack(self, **overrides):
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({**self.attack, **overrides}) + "\n")

    async def start_bridge(self):
        self.enterContext(patch.dict(os.environ, self.environment, clear=True))
        self.enterContext(patch("main.load_environment", return_value=self.root))
        self.enterContext(patch("main.httpx.AsyncClient", return_value=self.client))
        self.enterContext(patch("main.EventQueue", return_value=self.queue))
        self.enterContext(patch("main.EventStore", return_value=self.store))
        task = asyncio.create_task(main())

        async def stop():
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(self.client.is_closed)

        self.addAsyncCleanup(stop)
        await asyncio.wait_for(self.requested.wait(), timeout=5)
        return task

    async def take_event(self):
        return await asyncio.wait_for(self.saved_events.get(), timeout=5)

    async def test_local_model_scores_without_google_configuration(self):
        self.environment["LLM_MODEL_TYPE"] = "local"
        del self.environment["GOOGLE_API_KEY"]
        self.append_attack()
        await self.start_bridge()
        events = [await self.take_event(), await self.take_event()]
        self.assertCountEqual([event.danger_score for event in events], [60, 80])
        self.assertTrue(all(event.scoring_method == "llm" for event in events))
        self.model_factory.assert_not_called()

    async def test_both_sources_feed_one_queue_and_continue_after_startup(self):
        self.append_attack()
        await self.start_bridge()
        events = [await self.take_event(), await self.take_event()]
        self.assertCountEqual([event.log for event in events], [AttackLog.from_json(self.attack), LegacyLog.from_json(self.legacy)])
        self.assertCountEqual([event.danger_score for event in events], [80, 60])
        self.assertTrue(all(event.scoring_method == "llm" for event in events))
        self.append_attack(severity=3)
        event = await self.take_event()
        self.assertEqual(event.log, AttackLog.from_json({**self.attack, "severity": 3}))
        self.assertEqual(event.danger_score, 30)
        self.assertEqual(event.insight, ("Observed event", "No confirmed compromise"))
        self.assertEqual(event.respondsuggested, ("Review related logs", "Verify activity"))
        self.assertEqual(self.store.snapshot(), (*events, event))
        await asyncio.wait_for(self.queue.join(), timeout=5)
        self.assertEqual(self.queue.qsize(), 0)

    async def test_api_failure_does_not_stop_file_ingestion(self):
        self.status = 503
        self.append_attack()
        with self.assertLogs("ingestion.legacy_api_poller", level="WARNING"):
            await self.start_bridge()
            event = await self.take_event()
            self.assertEqual(event.log, AttackLog.from_json(self.attack))
            self.assertEqual(event.danger_score, 80)

    async def test_processed_events_are_stored_before_broadcast(self):
        broadcaster = EventBroadcaster(capacity=10)
        self.enterContext(patch("main.EventBroadcaster", return_value=broadcaster))
        self.append_attack()
        with broadcaster.subscribe() as subscriber:
            await self.start_bridge()
            for _ in range(2):
                event = await asyncio.wait_for(subscriber.receive(), timeout=5)
                self.assertIn(event, self.store.snapshot())
                self.assertEqual(event, await self.take_event())

    async def test_full_queue_backpressure_and_shutdown(self):
        async def wait_for_model(*args, **kwargs):
            await asyncio.Event().wait()

        class ObservedQueue(EventQueue):
            def __init__(self):
                super().__init__(capacity=1)
                self.put_attempts = 0
                self.third_put = asyncio.Event()

            async def put(self, event):
                self.put_attempts += 1
                if self.put_attempts == 3:
                    self.third_put.set()
                await super().put(event)

        self.queue = ObservedQueue()
        self.model_invoke.side_effect = wait_for_model
        self.environment["EVENT_QUEUE_CAPACITY"] = "1"
        self.append_attack()
        self.append_attack(severity=3)
        task = await self.start_bridge()
        await asyncio.wait_for(self.queue.third_put.wait(), timeout=5)
        self.assertEqual(self.queue.qsize(), 1)
        self.assertFalse(task.done())

    async def test_scoring_failure_keeps_pipeline_running_and_broadcasts_unscored_event(self):
        self.model_invoke.side_effect = RuntimeError("scoring failed")
        broadcaster = EventBroadcaster(capacity=10)
        self.enterContext(patch("main.EventBroadcaster", return_value=broadcaster))
        self.append_attack()
        with broadcaster.subscribe() as subscriber:
            task = await self.start_bridge()
            self.assertEqual(self.model_factory.call_args.kwargs["max_retries"], 0)
            for _ in range(2):
                event = await self.take_event()
                self.assertIsNone(event.danger_score)
                self.assertEqual(event.insight, ())
                self.assertEqual(event.respondsuggested, ())
                self.assertEqual(await asyncio.wait_for(subscriber.receive(), timeout=5), event)
            self.assertFalse(task.done())
            self.assertFalse(self.client.is_closed)
            self.model_invoke.side_effect = None
            self.model_invoke.return_value = AIMessage(content=json.dumps({
                "danger_score": 30, "insight": ["one", "two"], "respondsuggested": ["one", "two"],
            }))
            self.append_attack(severity=3)
            self.assertEqual((await self.take_event()).danger_score, 30)
            self.assertEqual(self.model_invoke.await_count, 3)

if __name__ == "__main__":
    unittest.main()