import asyncio
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx

from ingestion.legacy_api_poller import LegacyApiPoller, main
from models import LegacyLog


def make_poller(client, on_event, **overrides):
    settings = {
        "url": "http://localhost:5195/api/raw-logs",
        "interval_seconds": 2.0,
        "timeout_seconds": 5.0,
        "dedup_capacity": 10_000,
        **overrides,
    }
    return LegacyApiPoller(client, on_event, **settings)


def sample_log(**overrides):
    return {
        "timestamp": "2026-09-11T14:30:00+05:30",
        "source": "45.33.22.11",
        "event": "SSH Connection",
        "status": "Failed",
        **overrides,
    }


class LegacyApiPollerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.payload = [sample_log()]
        self.status = 200
        self.requests = []

        def respond(request):
            self.requests.append(request)
            return httpx.Response(self.status, json=self.payload)

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.sink = AsyncMock()
        self.poller = make_poller(self.client, self.sink)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_valid_records_are_delivered_only_once(self):
        self.payload.append(sample_log())
        self.assertEqual(await self.poller.poll_once(), 1)
        self.assertEqual(await self.poller.poll_once(), 0)
        self.sink.assert_awaited_once_with(LegacyLog.from_json(sample_log()))
        self.assertEqual(str(self.requests[0].url), "http://localhost:5195/api/raw-logs")
        self.assertEqual(self.requests[0].extensions["timeout"]["read"], 5.0)
        self.assertFalse(self.client.is_closed)

    async def test_changed_record_is_a_new_event(self):
        await self.poller.poll_once()
        self.payload.append(sample_log(status="Success"))
        self.assertEqual(await self.poller.poll_once(), 1)
        self.assertEqual(self.sink.await_count, 2)

    async def test_invalid_records_do_not_block_valid_records(self):
        self.payload = [
            None,
            {},
            sample_log(timestamp="invalid"),
            sample_log(source="invalid"),
            sample_log(status=42),
            sample_log(event=" "),
            sample_log(),
        ]
        with self.assertLogs("ingestion.legacy_api_poller", level="WARNING") as captured:
            self.assertEqual(await self.poller.poll_once(), 1)
        self.assertEqual(len(captured.output), 6)

    async def test_http_error_is_not_delivered(self):
        self.status = 503
        with self.assertRaises(httpx.HTTPStatusError):
            await self.poller.poll_once()
        self.sink.assert_not_awaited()

    async def test_non_array_payload_is_rejected(self):
        self.payload = {"error": "unavailable"}
        with self.assertRaises(ValueError):
            await self.poller.poll_once()
        self.sink.assert_not_awaited()

    async def test_invalid_json_is_rejected(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text="invalid"))
        ) as client:
            poller = make_poller(client, self.sink)
            with self.assertRaises(ValueError):
                await poller.poll_once()
        self.sink.assert_not_awaited()

    async def test_handler_failure_does_not_mark_event_as_delivered(self):
        self.sink.side_effect = [RuntimeError("Handler unavailable"), None]
        with self.assertRaises(RuntimeError):
            await self.poller.poll_once()
        self.assertEqual(await self.poller.poll_once(), 1)
        self.assertEqual(await self.poller.poll_once(), 0)
        self.assertEqual(self.sink.await_count, 2)

    async def test_deduplication_memory_is_bounded(self):
        poller = make_poller(self.client, self.sink, dedup_capacity=1)
        await poller.poll_once()
        self.payload = [sample_log(status="Success")]
        await poller.poll_once()
        self.payload = [sample_log()]
        self.assertEqual(await poller.poll_once(), 1)

    async def test_run_recovers_from_timeout_and_stops_on_cancellation(self):
        delivered = asyncio.Event()
        attempts = 0

        def respond(request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ReadTimeout("Private failure details", request=request)
            return httpx.Response(200, json=[sample_log()])

        async def accept(event):
            delivered.set()

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            poller = make_poller(client, accept, interval_seconds=0.001)
            with self.assertLogs("ingestion.legacy_api_poller", level="WARNING") as captured:
                task = asyncio.create_task(poller.run())
                try:
                    await asyncio.wait_for(delivered.wait(), timeout=1)
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
            self.assertGreaterEqual(attempts, 2)
            self.assertNotIn("Private failure details", " ".join(captured.output))
            self.assertFalse(client.is_closed)

    async def test_cancellation_during_delivery_propagates(self):
        self.sink.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.poller.run()

    async def test_configuration_is_validated(self):
        for options in (
            {"interval_seconds": 0},
            {"interval_seconds": float("nan")},
            {"timeout_seconds": -1},
            {"timeout_seconds": float("inf")},
            {"dedup_capacity": 0},
            {"dedup_capacity": 1.5},
            {"url": "ftp://localhost/logs"},
            {"url": "/api/raw-logs"},
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    make_poller(self.client, self.sink, **options)

    async def test_main_loads_dotenv_and_preserves_environment_overrides(self):
        with TemporaryDirectory() as directory:
            module_path = Path(directory) / "legacy_api_poller.py"
            module_path.with_name(".env").write_text(
                "LEGACYCORE_ENDPOINT=http://localhost:6200/api/raw-logs\n"
                "LEGACY_POLL_INTERVAL_SECONDS=3\n"
                "LEGACY_REQUEST_TIMEOUT_SECONDS=8\n"
                "LEGACY_DEDUP_CAPACITY=200\n",
                encoding="utf-8",
            )
            module_path.with_name(".env-prod").write_text(
                "LEGACYCORE_ENDPOINT=http://localhost:7200/api/raw-logs\n"
                "LEGACY_POLL_INTERVAL_SECONDS=10\n"
                "LEGACY_REQUEST_TIMEOUT_SECONDS=8\n"
                "LEGACY_DEDUP_CAPACITY=200\n",
                encoding="utf-8",
            )
            for environment, expected_interval, expected_port in (
                ({}, 3.0, 6200),
                ({"APP_ENV": "development"}, 3.0, 6200),
                ({"APP_ENV": "dev"}, 3.0, 6200),
                ({"LEGACY_POLL_INTERVAL_SECONDS": "7"}, 7.0, 6200),
                ({"APP_ENV": "production"}, 10.0, 7200),
                ({"APP_ENV": "prod"}, 10.0, 7200),
                ({"APP_ENV": "production", "LEGACY_POLL_INTERVAL_SECONDS": "7"}, 7.0, 7200),
            ):
                with self.subTest(environment=environment):
                    with (
                        patch.dict(os.environ, environment, clear=True),
                        patch("configuration.__file__", str(module_path.parent / "configuration" / "__init__.py")),
                        patch("ingestion.legacy_api_poller.LegacyApiPoller") as poller_class,
                    ):
                        poller_class.return_value.run = AsyncMock()
                        await main()
                        self.assertEqual(poller_class.call_args.kwargs, {
                            "url": f"http://localhost:{expected_port}/api/raw-logs",
                            "interval_seconds": expected_interval,
                            "timeout_seconds": 8.0,
                            "dedup_capacity": 200,
                        })
                        poller_class.return_value.run.assert_awaited_once()

    async def test_production_does_not_fall_back_to_development_file(self):
        with TemporaryDirectory() as directory:
            module_path = Path(directory) / "legacy_api_poller.py"
            module_path.with_name(".env").write_text(
                "LEGACYCORE_ENDPOINT=http://localhost:6200/api/raw-logs\n",
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {"APP_ENV": "production"}, clear=True),
                patch("configuration.__file__", str(module_path.parent / "configuration" / "__init__.py")),
            ):
                with self.assertRaisesRegex(KeyError, "LEGACYCORE_ENDPOINT"):
                    await main()

    async def test_unknown_environment_is_rejected(self):
        with patch.dict(os.environ, {"APP_ENV": "produciton"}, clear=True):
            with self.assertRaisesRegex(ValueError, "APP_ENV"):
                await main()

    async def test_main_requires_configuration_without_hardcoded_defaults(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("configuration.load_dotenv"),
        ):
            with self.assertRaisesRegex(KeyError, "LEGACYCORE_ENDPOINT"):
                await main()


if __name__ == "__main__":
    unittest.main()