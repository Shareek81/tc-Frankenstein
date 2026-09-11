import asyncio
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

import httpx
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from integrations import LlmScorer
from integrations.llm_scorer import DangerScoreResponse
from main import main, print_event_store
from messaging.event_queue import EventQueue
from models import AttackLog, ILog, LegacyLog
from processing import EventProcessor
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
            return AIMessage(content=json.dumps({"danger_score": score}))

        self.model = FakeListChatModel(responses=['{"danger_score": 80}'])
        self.model_invoke = self.enterContext(patch.object(
            FakeListChatModel, "ainvoke", new=AsyncMock(side_effect=respond_to_log),
        ))
        self.model_factory = self.enterContext(patch("integrations.model_strategies.ChatGoogleGenerativeAI", return_value=self.model))
        self.local_model_factory = self.enterContext(patch("integrations.model_strategies.ChatOllama", return_value=self.model))

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
        queue_factory = self.enterContext(patch("main.EventQueue", return_value=self.queue))
        store_factory = self.enterContext(patch("main.EventStore", return_value=self.store))
        task = asyncio.create_task(main())

        async def stop():
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(self.client.is_closed)

        self.addAsyncCleanup(stop)
        await asyncio.wait_for(self.requested.wait(), timeout=5)
        queue_factory.assert_called_once_with(capacity=int(self.environment["EVENT_QUEUE_CAPACITY"]))
        store_factory.assert_called_once_with(capacity=int(self.environment["EVENT_STORE_CAPACITY"]))
        if self.environment["LLM_MODEL_TYPE"] == "local":
            self.local_model_factory.assert_called_once_with(
                model="test-model", temperature=0,
                format=DangerScoreResponse.model_json_schema(),
            )
            self.model_factory.assert_not_called()
        else:
            self.model_factory.assert_called_once_with(
                model="test-model", temperature=0, timeout=None,
            )
            self.local_model_factory.assert_not_called()
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

    async def test_store_printer_outputs_changed_snapshots_only(self):
        await self.queue.put(AttackLog.from_json(self.attack))
        event = await EventProcessor(self.queue, LlmScorer(self.model), self.store).process_once()
        with (
            patch("builtins.print") as output,
            patch("main.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError()])),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await print_event_store(self.store)
        output.assert_called_once()
        payload = json.loads(output.call_args.args[0])
        self.assertEqual(payload["event_store"][0]["event_id"], event.event_id)
        self.assertEqual(payload["event_store"][0]["danger_score"], 80)
        self.assertEqual(payload["event_store"][0]["log"], self.attack)
        self.assertTrue(output.call_args.kwargs["flush"])

    async def test_scoring_failure_stops_pipeline_and_closes_client(self):
        self.model_invoke.side_effect = RuntimeError("scoring failed")

        self.append_attack()
        self.enterContext(patch.dict(os.environ, self.environment, clear=True))
        self.enterContext(patch("main.load_environment", return_value=self.root))
        self.enterContext(patch("main.httpx.AsyncClient", return_value=self.client))
        self.enterContext(patch("main.EventStore", return_value=self.store))
        with self.assertRaises(ExceptionGroup) as raised:
            await asyncio.wait_for(main(), timeout=5)
        self.assertEqual(len(raised.exception.exceptions), 1)
        self.assertIsInstance(raised.exception.exceptions[0], RuntimeError)
        self.assertTrue(self.client.is_closed)
        self.assertEqual(self.store.snapshot(), ())

    async def test_printer_accepts_read_only_store_and_non_dataclass_log(self):
        class CustomLog(ILog):
            def to_payload(self) -> dict[str, object]:
                return {"event": "custom activity"}

            @classmethod
            def from_json(cls, payload):
                return cls()

        scorer = Mock(score=AsyncMock(return_value=50))
        scorer.name = "test"
        log = CustomLog()
        await self.queue.put(log)
        event = await EventProcessor(self.queue, scorer, self.store).process_once()

        class ReadOnlyStore:
            def snapshot(self):
                return (event,)

        with (
            patch("builtins.print") as output,
            patch("main.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError())),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await print_event_store(ReadOnlyStore())
        payload = json.loads(output.call_args.args[0])["event_store"][0]
        self.assertEqual(payload["log"], log.to_payload())
        self.assertEqual(payload["processed_at"], event.processed_at.isoformat())
        self.assertEqual(payload["danger_score"], 50)


if __name__ == "__main__":
    unittest.main()