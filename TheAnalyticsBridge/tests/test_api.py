import asyncio
import json
import socket
import unittest
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import datetime, time, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import uvicorn

from api.app import create_app
from api.routes import stream_events
from integrations.geolocation import IpLocation
from messaging.event_broadcaster import EventBroadcaster
from messaging.event_stream import EventStream
from models import AttackLog, ProcessedEvent
from storage import EventStore


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = EventStore(capacity=3)
        self.disconnected = asyncio.Event()

        class ObservedBroadcaster(EventBroadcaster):
            @contextmanager
            def subscribe(broadcaster):
                try:
                    with super().subscribe() as subscription:
                        yield subscription
                finally:
                    self.disconnected.set()

        self.broadcaster = ObservedBroadcaster(capacity=2)
        self.stream = EventStream(self.store, self.store, self.broadcaster, self.broadcaster)
        self.event = ProcessedEvent(
            "first", AttackLog(time(14, 30), "Brute Force", 8, "192.0.2.1"),
            80, "test", datetime.now(timezone.utc),
            insight=("High reported severity", "No confirmed compromise in this log"),
            respondsuggested=("Review authentication logs", "Verify account activity"),
        )
        self.stream.append(self.event)
        self.runtime_closed = False
        self.fail_worker = asyncio.Event()
        self.runtime_stopped = asyncio.Event()

        async def worker():
            await self.fail_worker.wait()
            raise RuntimeError("test worker failure")

        @asynccontextmanager
        async def runtime():
            try:
                async with asyncio.TaskGroup() as tasks:
                    task = tasks.create_task(worker())
                    try:
                        yield self.stream
                    finally:
                        task.cancel()
            finally:
                self.broadcaster.close()
                self.runtime_closed = True
                self.runtime_stopped.set()

        self.simulator_control = Mock(request_stop=AsyncMock())
        self.app = create_app(runtime, heartbeat_seconds=0.05, simulator_control=self.simulator_control)
        ready = asyncio.Event()

        class TestServer(uvicorn.Server):
            async def startup(server, sockets=None):
                await super().startup(sockets=sockets)
                ready.set()

        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.addCleanup(self.socket.close)
        self.server = TestServer(uvicorn.Config(self.app, log_level="critical", timeout_graceful_shutdown=1))
        self.server_task = asyncio.create_task(self.server.serve(sockets=[self.socket]))

        async def stop():
            self.server.should_exit = True
            await asyncio.wait_for(self.server_task, timeout=5)
            self.assertTrue(self.runtime_closed)
            self.assertEqual(self.broadcaster.subscriber_count, 0)

        self.addAsyncCleanup(stop)
        await asyncio.wait_for(ready.wait(), timeout=5)
        self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{self.socket.getsockname()[1]}", trust_env=False)
        self.addAsyncCleanup(self.client.aclose)

    async def next_frame(self, lines):
        async with asyncio.timeout(3):
            fields = {}
            async for line in lines:
                if not line and fields:
                    return fields
                if line.startswith(":"):
                    continue
                if ":" in line:
                    name, value = line.split(":", 1)
                    fields[name] = value.lstrip()
        self.fail("Stream ended before an SSE event")

    async def test_history_and_health_endpoints(self):
        response = await self.client.get("/api/events")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [self.event.to_payload()])
        self.assertEqual(response.json()[0]["insight"], list(self.event.insight))
        self.assertEqual(response.json()[0]["respondsuggested"], list(self.event.respondsuggested))
        self.assertEqual((await self.client.get("/api/health")).json(), {"status": "ok"})

    async def test_unscored_event_survives_history_and_sse(self):
        event = replace(self.event, event_id="unscored", danger_score=None,
                        scoring_method="unavailable", insight=(), respondsuggested=())
        self.stream.append(event)
        payload = (await self.client.get("/api/events")).json()[-1]
        self.assertEqual(payload, event.to_payload())
        self.assertIsNone(payload["danger_score"])
        async with self.client.stream("GET", "/api/stream") as response:
            lines = response.aiter_lines()
            snapshot = await self.next_frame(lines)
            self.assertEqual(json.loads(snapshot["data"])[-1], payload)
            live = replace(event, event_id="live-unscored")
            self.stream.append(live)
            frame = await self.next_frame(lines)
            self.assertEqual(json.loads(frame["data"]), live.to_payload())

    async def test_built_dashboard_and_api_share_origin(self):
        if not (Path(__file__).resolve().parents[2] / "TheCommandCenter" / "dist").is_dir():
            self.skipTest("Build TheCommandCenter to verify static serving")
        response = await self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Frankenstein | Threat Command Center", response.text)
        self.assertEqual((await self.client.get("/earth.jpg")).status_code, 200)
        self.assertEqual((await self.client.get("/docs")).status_code, 200)
        self.assertEqual((await self.client.get("/api/events")).status_code, 200)

    async def test_ip_location_validation_and_private_addresses(self):
        self.assertEqual((await self.client.get("/api/locations/not-an-ip")).status_code, 422)
        response = await self.client.get("/api/locations/192.168.1.1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "non_public")
        self.assertIsNone(response.json()["latitude"])

    async def test_ip_location_success_and_provider_failure(self):
        result = IpLocation(ip="8.8.8.8", status="located", latitude=37.4, longitude=-122.1)
        with patch("api.routes.IpGeolocation.locate", new_callable=AsyncMock) as locate:
            locate.return_value = result
            response = await self.client.get("/api/locations/8.8.8.8")
            self.assertEqual(response.json(), result.model_dump())
            locate.assert_awaited_once_with("8.8.8.8")
            locate.side_effect = httpx.ConnectError("provider unavailable")
            self.assertEqual((await self.client.get("/api/locations/8.8.8.8")).status_code, 503)
        self.assertEqual((await self.client.get("/api/events")).status_code, 200)

    async def test_stop_simulator_requests_shutdown_without_stopping_api(self):
        for _ in range(2):
            response = await self.client.post("/api/simulator/stop")
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), {"status": "stop_requested"})
        self.assertEqual(self.simulator_control.request_stop.await_count, 2)
        self.assertEqual((await self.client.get("/api/health")).status_code, 200)
        self.assertEqual((await self.client.get("/api/events")).json(), [self.event.to_payload()])

    async def test_stop_simulator_requires_post(self):
        response = await self.client.get("/api/simulator/stop")
        self.assertEqual(response.status_code, 405)
        self.simulator_control.request_stop.assert_not_awaited()

    async def test_stop_simulator_io_failure_returns_unavailable(self):
        self.simulator_control.request_stop.side_effect = PermissionError("private path")
        response = await self.client.post("/api/simulator/stop")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Simulator control is unavailable"})

    async def test_stop_simulator_works_after_processing_failure(self):
        self.fail_worker.set()
        await asyncio.wait_for(self.runtime_stopped.wait(), timeout=3)
        response = await self.client.post("/api/simulator/stop")
        self.assertEqual(response.status_code, 202)
        self.simulator_control.request_stop.assert_awaited_once()

    async def test_worker_failure_makes_endpoints_unavailable(self):
        self.fail_worker.set()
        await asyncio.wait_for(self.runtime_stopped.wait(), timeout=3)
        for endpoint in ("/api/health", "/api/events", "/api/stream"):
            response = await self.client.get(endpoint)
            self.assertEqual(response.status_code, 503)

    async def test_http_disconnect_unregisters_subscriber(self):
        async with self.client.stream("GET", "/api/stream") as response:
            await self.next_frame(response.aiter_lines())
            self.assertEqual(self.broadcaster.subscriber_count, 1)
        await asyncio.wait_for(self.disconnected.wait(), timeout=3)
        self.assertEqual(self.broadcaster.subscriber_count, 0)

    async def test_empty_snapshot_is_sent_immediately(self):
        empty_store = EventStore(capacity=1)
        self.app.state.event_feed = EventStream(empty_store, empty_store, self.broadcaster, self.broadcaster)
        async with self.client.stream("GET", "/api/stream") as response:
            frame = await self.next_frame(response.aiter_lines())
            self.assertEqual(frame["event"], "snapshot")
            self.assertEqual(json.loads(frame["data"]), [])

    async def test_snapshot_then_broadcast_to_two_http_clients(self):
        async with self.client.stream("GET", "/api/stream") as first, self.client.stream("GET", "/api/stream") as second:
            self.assertEqual(first.status_code, 200)
            self.assertIn("text/event-stream", first.headers["content-type"])
            self.assertEqual(first.headers["x-accel-buffering"], "no")
            first_lines, second_lines = first.aiter_lines(), second.aiter_lines()
            for lines in (first_lines, second_lines):
                frame = await self.next_frame(lines)
                self.assertEqual(frame["event"], "snapshot")
                self.assertEqual(json.loads(frame["data"]), [self.event.to_payload()])
            event = replace(self.event, event_id="second")
            self.stream.append(event)
            for lines in (first_lines, second_lines):
                frame = await self.next_frame(lines)
                self.assertEqual(frame["event"], "log")
                self.assertEqual(frame["id"], "second")
                self.assertEqual(json.loads(frame["data"]), event.to_payload())

    async def test_reconnect_with_last_id_receives_replacement_snapshot(self):
        self.stream.append(replace(self.event, event_id="second"))
        async with self.client.stream("GET", "/api/stream", headers={"Last-Event-ID": "first"}) as response:
            frame = await self.next_frame(response.aiter_lines())
            self.assertEqual(frame["event"], "snapshot")
            self.assertEqual([event["event_id"] for event in json.loads(frame["data"])], ["first", "second"])

    async def test_idle_stream_sends_heartbeat(self):
        async with self.client.stream("GET", "/api/stream") as response:
            lines = response.aiter_lines()
            await self.next_frame(lines)
            async with asyncio.timeout(2):
                async for line in lines:
                    if line.startswith(": ping"):
                        break
                else:
                    self.fail("No heartbeat received")

    async def test_generator_overflow_requests_reset_and_cleans_up(self):
        generator = stream_events(self.stream)
        self.assertEqual((await anext(generator))["event"], "snapshot")
        for index in range(3):
            self.stream.append(replace(self.event, event_id=str(index)))
        self.assertEqual((await anext(generator))["event"], "reset")
        with self.assertRaises(StopAsyncIteration):
            await anext(generator)
        self.assertEqual(self.broadcaster.subscriber_count, 0)

    async def test_generator_cancellation_unregisters_subscriber(self):
        generator = stream_events(self.stream)
        await anext(generator)
        waiter = asyncio.create_task(anext(generator))
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        await generator.aclose()
        self.assertEqual(self.broadcaster.subscriber_count, 0)


if __name__ == "__main__":
    unittest.main()