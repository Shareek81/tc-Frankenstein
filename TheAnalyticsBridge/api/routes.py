import json
from collections.abc import AsyncIterator
from ipaddress import IPv4Address, IPv6Address

import httpx
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from integrations.simulator import SimulatorControl
from integrations.geolocation import IpGeolocation, IpLocation
from messaging.contracts import EventFeed
from messaging.exceptions import StreamClosed
from processing.contracts import EventReader


async def stream_events(feed: EventFeed) -> AsyncIterator[dict[str, str | int]]:
    try:
        with feed.connect() as connection:
            yield {
                "event": "snapshot",
                "data": json.dumps([event.to_payload() for event in connection.history]),
                "retry": 2000,
            }
            while True:
                event = await connection.subscription.receive()
                yield {"event": "log", "id": event.event_id, "data": json.dumps(event.to_payload())}
    except StreamClosed:
        yield {"event": "reset", "data": json.dumps({"reason": "resync_required"}), "retry": 2000}


def create_router(
    *, heartbeat_seconds: float, send_timeout_seconds: float,
    simulator_control: SimulatorControl,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    geolocation = IpGeolocation()

    @router.get("/locations/{address}")
    async def location(address: IPv4Address | IPv6Address) -> IpLocation:
        try:
            return await geolocation.locate(str(address))
        except (httpx.HTTPError, ValueError):
            raise HTTPException(status_code=503, detail="Location lookup unavailable; try again later") from None

    @router.post("/simulator/stop", status_code=202)
    async def stop_simulator() -> dict[str, str]:
        try:
            await simulator_control.request_stop()
        except OSError:
            raise HTTPException(status_code=503, detail="Simulator control is unavailable") from None
        return {"status": "stop_requested"}

    @router.get("/events")
    async def history(request: Request) -> list[dict[str, object]]:
        reader: EventReader | None = getattr(request.app.state, "event_reader", None)
        if reader is None:
            raise HTTPException(status_code=503, detail="Event processing is unavailable")
        return [event.to_payload() for event in reader.snapshot()]

    @router.get("/stream", response_class=EventSourceResponse)
    async def stream(request: Request) -> EventSourceResponse:
        feed: EventFeed | None = getattr(request.app.state, "event_feed", None)
        if feed is None:
            raise HTTPException(status_code=503, detail="Event processing is unavailable")
        return EventSourceResponse(
            stream_events(feed),
            ping=heartbeat_seconds,
            send_timeout=send_timeout_seconds,
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @router.get("/health")
    async def health(request: Request) -> dict[str, str]:
        if getattr(request.app.state, "event_feed", None) is None:
            raise HTTPException(status_code=503, detail="Event processing is unavailable")
        return {"status": "ok"}

    return router