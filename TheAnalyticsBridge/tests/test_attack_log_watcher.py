import asyncio
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

from watchdog.events import DirModifiedEvent, FileCreatedEvent, FileModifiedEvent, FileOpenedEvent
from watchdog.observers import Observer

from ingestion.attack_log_watcher import AttackLogWatcher, _LogChangeHandler, main
from models import AttackLog


def sample_attack(**overrides):
    return {
        "time": "14:30:00",
        "type": "Brute Force",
        "severity": 8,
        "origin": "103.25.12.45",
        **overrides,
    }


class AttackLogWatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "live_stream.log"
        self.sink = AsyncMock()
        self.watcher = AttackLogWatcher(
            self.sink, log_path=self.path, retry_interval_seconds=0.05
        )

    def append(self, record=None):
        with self.path.open("ab") as stream:
            stream.write((json.dumps(record or sample_attack()) + "\r\n").encode("utf-8"))

    async def test_reads_existing_and_new_lines_without_rereading(self):
        self.append()
        self.assertEqual(await self.watcher.read_once(), 1)
        self.assertEqual(await self.watcher.read_once(), 0)
        self.append()
        self.assertEqual(await self.watcher.read_once(), 1)
        self.assertEqual(self.sink.await_count, 2)
        self.sink.assert_awaited_with(AttackLog.from_json(sample_attack()))

    async def test_waits_for_complete_line_including_split_utf8(self):
        encoded = json.dumps(sample_attack(type="Test \u00e9"), ensure_ascii=False).encode("utf-8")
        split = encoded.index(b"\xc3") + 1
        self.path.write_bytes(encoded[:split])
        self.assertEqual(await self.watcher.read_once(), 0)
        with self.path.open("ab") as stream:
            stream.write(encoded[split:])
        self.assertEqual(await self.watcher.read_once(), 0)
        with self.path.open("ab") as stream:
            stream.write(b"\n")
        self.assertEqual(await self.watcher.read_once(), 1)

    async def test_waits_for_initial_file_creation(self):
        self.assertEqual(await self.watcher.read_once(), 0)
        self.append()
        self.assertEqual(await self.watcher.read_once(), 1)
        self.assertEqual(await self.watcher.read_once(), 0)

    async def test_invalid_complete_lines_are_skipped(self):
        self.path.write_bytes(b"not json\n\xff\n{}\n\n")
        self.append()
        with self.assertLogs("ingestion.attack_log_watcher", level="WARNING") as logs:
            self.assertEqual(await self.watcher.read_once(), 1)
        self.assertEqual(len(logs.output), 4)
        self.assertEqual(await self.watcher.read_once(), 0)

    async def test_utf8_bom_is_accepted(self):
        self.path.write_bytes(b"\xef\xbb\xbf")
        self.append()
        self.assertEqual(await self.watcher.read_once(), 1)

    async def test_failed_delivery_retries_only_unaccepted_line(self):
        self.append()
        self.append(sample_attack(severity=4))
        self.sink.side_effect = [None, RuntimeError("Unavailable"), None]
        with self.assertRaises(RuntimeError):
            await self.watcher.read_once()
        self.assertEqual(await self.watcher.read_once(), 1)
        self.assertEqual(await self.watcher.read_once(), 0)
        self.assertEqual(self.sink.await_count, 3)

    async def test_concurrent_reads_are_serialized(self):
        self.append()
        counts = await asyncio.gather(self.watcher.read_once(), self.watcher.read_once())
        self.assertEqual(sum(counts), 1)
        self.sink.assert_awaited_once()

    async def test_batches_are_drained_in_order(self):
        for _ in range(105):
            self.append()
        self.assertEqual(await self.watcher.read_once(), 100)
        self.assertEqual(await self.watcher.read_once(), 5)
        self.assertEqual(await self.watcher.read_once(), 0)

    async def test_real_observer_delivers_appends_and_stops_on_cancellation(self):
        queue = asyncio.Queue()
        observer = Observer()
        watcher = AttackLogWatcher(queue.put, log_path=self.path, retry_interval_seconds=60)
        self.append()
        with patch("ingestion.attack_log_watcher.Observer", return_value=observer):
            task = asyncio.create_task(watcher.run())
            try:
                await asyncio.wait_for(queue.get(), timeout=5)
                self.append(sample_attack(severity=2))
                event = await asyncio.wait_for(queue.get(), timeout=5)
                self.assertEqual(event.severity, 2)
                self.assertTrue(queue.empty())
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertFalse(observer.is_alive())

    async def test_run_retries_handler_failure_without_another_write(self):
        delivered = asyncio.Event()
        attempts = 0

        async def accept(event):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("Private payload")
            delivered.set()

        self.append()
        watcher = AttackLogWatcher(accept, log_path=self.path, retry_interval_seconds=0.01)
        with self.assertLogs("ingestion.attack_log_watcher", level="WARNING") as logs:
            task = asyncio.create_task(watcher.run())
            try:
                await asyncio.wait_for(delivered.wait(), timeout=5)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertEqual(attempts, 2)
        self.assertNotIn("Private payload", " ".join(logs.output))

    async def test_missing_directory_fails_at_startup(self):
        watcher = AttackLogWatcher(
            self.sink, log_path=self.path.parent / "missing" / "stream.log", retry_interval_seconds=1
        )
        with self.assertRaises(FileNotFoundError):
            await watcher.run()

    async def test_configuration_is_validated(self):
        for interval in (0, -1, float("nan"), float("inf")):
            with self.subTest(interval=interval):
                with self.assertRaises(ValueError):
                    AttackLogWatcher(self.sink, log_path=self.path, retry_interval_seconds=interval)

    async def test_main_loads_selected_environment_and_resolves_log_path(self):
        module_path = self.path.parent / "attack_log_watcher.py"
        module_path.with_name(".env").write_text(
            "ATTACK_LOG_PATH=dev.log\nATTACK_WATCH_RETRY_SECONDS=2\n", encoding="utf-8"
        )
        module_path.with_name(".env-prod").write_text(
            "ATTACK_LOG_PATH=prod.log\nATTACK_WATCH_RETRY_SECONDS=5\n", encoding="utf-8"
        )
        for environment, expected_name, expected_retry in (
            ({}, "dev.log", 2.0),
            ({"APP_ENV": "production"}, "prod.log", 5.0),
            ({"APP_ENV": "prod", "ATTACK_WATCH_RETRY_SECONDS": "7"}, "prod.log", 7.0),
        ):
            with self.subTest(environment=environment):
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch("configuration.__file__", str(module_path.parent / "configuration" / "__init__.py")),
                    patch("ingestion.attack_log_watcher.AttackLogWatcher") as watcher_class,
                ):
                    watcher_class.return_value.run = AsyncMock()
                    await main()
                    self.assertEqual(watcher_class.call_args.kwargs, {
                        "log_path": module_path.resolve().parent / expected_name,
                        "retry_interval_seconds": expected_retry,
                    })
                    watcher_class.return_value.run.assert_awaited_once()

    async def test_main_requires_production_settings_without_development_fallback(self):
        module_path = self.path.parent / "attack_log_watcher.py"
        module_path.with_name(".env").write_text(
            "ATTACK_LOG_PATH=dev.log\nATTACK_WATCH_RETRY_SECONDS=2\n", encoding="utf-8"
        )
        with (
            patch.dict(os.environ, {"APP_ENV": "production"}, clear=True),
            patch("configuration.__file__", str(module_path.parent / "configuration" / "__init__.py")),
        ):
            with self.assertRaisesRegex(KeyError, "ATTACK_LOG_PATH"):
                await main()

    async def test_main_rejects_unknown_environment(self):
        with patch.dict(os.environ, {"APP_ENV": "invalid"}, clear=True):
            with self.assertRaisesRegex(ValueError, "APP_ENV"):
                await main()


class AttackLogTests(unittest.TestCase):
    def test_invalid_payloads_are_rejected(self):
        for payload in (
            None, {}, sample_attack(severity=True), sample_attack(severity="8"),
            sample_attack(severity=0), sample_attack(severity=10),
            sample_attack(time="25:00:00"), sample_attack(time="1:00:00"),
            sample_attack(origin="invalid"), sample_attack(type=" "),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    AttackLog.from_json(payload)

    def test_handler_filters_events_and_handles_creation(self):
        path = Path("live_stream.log").resolve()
        notify = Mock()
        handler = _LogChangeHandler(path, notify)
        for event in (
            DirModifiedEvent(str(path.parent)), FileOpenedEvent(str(path)),
            FileModifiedEvent(str(path.with_name("other.log"))),
        ):
            handler.on_any_event(event)
        notify.assert_not_called()
        handler.on_any_event(FileModifiedEvent(str(path)))
        handler.on_any_event(FileCreatedEvent(str(path)))
        self.assertEqual(notify.call_count, 2)


if __name__ == "__main__":
    unittest.main()