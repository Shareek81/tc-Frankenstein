import math
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from configuration.simulator import load_simulator_stop_path
from integrations.simulator import AttackSimulatorControl, SimulatorControl
from messaging.contracts import EventFeed
from processing.contracts import EventReader

from .routes import create_router


class ApiEvents(EventFeed, EventReader, Protocol):
    pass


def create_app(
    runtime_factory: Callable[[], AbstractAsyncContextManager[ApiEvents]] | None = None,
    *, heartbeat_seconds: float = 15, send_timeout_seconds: float = 30,
    simulator_control: SimulatorControl | None = None,
) -> FastAPI:
    for value in (heartbeat_seconds, send_timeout_seconds):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("SSE heartbeat and send timeout must be positive and finite")
    if runtime_factory is None:
        from main import bridge_runtime

        runtime_factory = bridge_runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with runtime_factory() as events:
            app.state.event_reader = events
            app.state.event_feed = events
            try:
                yield
            finally:
                del app.state.event_reader
                del app.state.event_feed

    app = FastAPI(title="Frankenstein Analytics Bridge", lifespan=lifespan)
    if simulator_control is None:
        simulator_control = AttackSimulatorControl(
            stop_path=load_simulator_stop_path(),
        )
    app.include_router(create_router(
        heartbeat_seconds=heartbeat_seconds, send_timeout_seconds=send_timeout_seconds,
        simulator_control=simulator_control,
    ))
    dashboard_path = Path(__file__).resolve().parents[2] / "TheCommandCenter" / "dist"
    if dashboard_path.is_dir():
        app.mount("/assets", StaticFiles(directory=dashboard_path / "assets"), name="command-center-assets")

        @app.get("/", include_in_schema=False)
        async def dashboard() -> FileResponse:
            return FileResponse(dashboard_path / "index.html")

        @app.get("/earth.jpg", include_in_schema=False)
        async def earth_texture() -> FileResponse:
            return FileResponse(dashboard_path / "earth.jpg")
    return app