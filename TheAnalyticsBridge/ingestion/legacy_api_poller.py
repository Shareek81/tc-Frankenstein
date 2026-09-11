import asyncio
import json
import logging
import math
import os
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import asdict

import httpx

from configuration import load_environment
from models import LegacyLog


logger = logging.getLogger(__name__)


class LegacyApiPoller:
    def __init__(
        self,
        client: httpx.AsyncClient,
        on_event: Callable[[LegacyLog], Awaitable[None]],
        *,
        url: str,
        interval_seconds: float,
        timeout_seconds: float,
        dedup_capacity: int,
    ) -> None:
        for value in (interval_seconds, timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Polling interval and timeout must be positive and finite")
        if isinstance(dedup_capacity, bool) or not isinstance(dedup_capacity, int) or dedup_capacity < 1:
            raise ValueError("Deduplication capacity must be a positive integer")
        parsed_url = httpx.URL(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.host:
            raise ValueError("Legacy API URL must be an absolute HTTP(S) URL")
        self._client = client
        self._on_event = on_event
        self._url = parsed_url
        self._interval = interval_seconds
        self._timeout = timeout_seconds
        self._dedup_capacity = dedup_capacity
        self._seen: OrderedDict[LegacyLog, None] = OrderedDict()

    async def poll_once(self) -> int:
        response = await self._client.get(self._url, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Legacy API must return a JSON array")

        accepted = 0
        for record in payload:
            try:
                event = LegacyLog.from_json(record)
            except ValueError:
                logger.warning("Skipping invalid legacy log")
                continue
            if event in self._seen:
                self._seen.move_to_end(event)
                continue
            await self._on_event(event)
            self._seen[event] = None
            if len(self._seen) > self._dedup_capacity:
                self._seen.popitem(last=False)
            accepted += 1
        return accepted

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("Legacy poll failed (%s); retrying next interval", type(error).__name__)
            await asyncio.sleep(self._interval)


async def main() -> None:
    load_environment()

    async def print_event(event: LegacyLog) -> None:
        print(json.dumps(asdict(event), default=str), flush=True)

    async with httpx.AsyncClient() as client:
        poller = LegacyApiPoller(
            client,
            print_event,
            url=os.environ["LEGACYCORE_ENDPOINT"],
            interval_seconds=float(os.environ["LEGACY_POLL_INTERVAL_SECONDS"]),
            timeout_seconds=float(os.environ["LEGACY_REQUEST_TIMEOUT_SECONDS"]),
            dedup_capacity=int(os.environ["LEGACY_DEDUP_CAPACITY"]),
        )
        await poller.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass