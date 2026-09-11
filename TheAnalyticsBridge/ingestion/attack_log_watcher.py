import asyncio
import json
import logging
import math
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from configuration import load_environment
from models import AttackLog


logger = logging.getLogger(__name__)


class _LogChangeHandler(FileSystemEventHandler):
    def __init__(self, path: Path, notify: Callable[[], None]) -> None:
        self._path = os.path.normcase(os.path.abspath(path))
        self._notify = notify

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in {"created", "modified"}:
            return
        if os.path.normcase(os.path.abspath(os.fsdecode(event.src_path))) == self._path:
            self._notify()


class AttackLogWatcher:
    def __init__(
        self,
        on_event: Callable[[AttackLog], Awaitable[None]],
        *,
        log_path: str | Path,
        retry_interval_seconds: float,
    ) -> None:
        if not math.isfinite(retry_interval_seconds) or retry_interval_seconds <= 0:
            raise ValueError("Retry interval must be positive and finite")
        self._path = Path(log_path).resolve()
        self._on_event = on_event
        self._retry_interval = retry_interval_seconds
        self._offset = 0
        self._read_lock = asyncio.Lock()
        self._running = False

    def _read_batch(self, offset: int) -> list[tuple[int, bytes]]:
        with self._path.open("rb") as stream:
            stream.seek(offset)
            records = []
            for _ in range(100):
                line = stream.readline()
                if not line.endswith(b"\n"):
                    break
                records.append((stream.tell(), line))
            return records

    async def read_once(self) -> int:
        async with self._read_lock:
            try:
                records = await asyncio.to_thread(self._read_batch, self._offset)
            except FileNotFoundError:
                return 0
            accepted = 0
            for end_offset, line in records:
                try:
                    event = AttackLog.from_json(json.loads(line.decode("utf-8-sig")))
                except (ValueError, UnicodeError):
                    logger.warning("Skipping invalid attack log line")
                else:
                    await self._on_event(event)
                    accepted += 1
                self._offset = end_offset
            return accepted

    async def run(self) -> None:
        if self._running:
            raise RuntimeError("The attack log watcher is already running")
        if not self._path.parent.is_dir():
            raise FileNotFoundError("The attack log directory must exist before starting the watcher")
        self._running = True
        changed = asyncio.Event()
        loop = asyncio.get_running_loop()
        observer = Observer()
        handler = _LogChangeHandler(self._path, lambda: loop.call_soon_threadsafe(changed.set))
        try:
            observer.schedule(handler, str(self._path.parent), recursive=False)
            observer.start()
            while True:
                changed.clear()
                try:
                    previous_offset = self._offset
                    await self.read_once()
                    if previous_offset != self._offset:
                        continue
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning("Attack log read failed (%s); retrying", type(error).__name__)
                try:
                    await asyncio.wait_for(changed.wait(), timeout=self._retry_interval)
                except TimeoutError:
                    pass
        finally:
            observer.stop()
            if observer.ident is not None:
                await asyncio.to_thread(observer.join)
            self._running = False


async def main() -> None:
    bridge_path = load_environment()
    log_path = Path(os.environ["ATTACK_LOG_PATH"])
    if not log_path.is_absolute():
        log_path = bridge_path / log_path

    async def print_event(event: AttackLog) -> None:
        print(json.dumps(asdict(event), default=str), flush=True)

    watcher = AttackLogWatcher(
        print_event,
        log_path=log_path,
        retry_interval_seconds=float(os.environ["ATTACK_WATCH_RETRY_SECONDS"]),
    )
    await watcher.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass