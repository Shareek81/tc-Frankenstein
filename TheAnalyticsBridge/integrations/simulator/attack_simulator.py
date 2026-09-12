import asyncio
from pathlib import Path
from typing import Protocol


class SimulatorControl(Protocol):
    async def request_stop(self) -> None: ...


class AttackSimulatorControl:
    def __init__(self, *, stop_path: Path) -> None:
        self._stop_path = stop_path

    async def request_stop(self) -> None:
        await asyncio.to_thread(self._stop_path.touch, exist_ok=True)