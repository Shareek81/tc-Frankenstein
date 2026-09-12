import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from configuration import load_environment
from ingestion.attack_log_watcher import AttackLogWatcher
from ingestion.legacy_api_poller import LegacyApiPoller
from integrations.llm import LlmScorer, create_chat_model
from messaging.event_queue import EventQueue
from messaging.event_broadcaster import EventBroadcaster
from messaging.event_stream import EventStream
from processing import EventProcessor
from storage import EventStore


logger = logging.getLogger(__name__)


@asynccontextmanager
async def bridge_runtime() -> AsyncIterator[EventStream]:
    bridge_path = load_environment()
    queue = EventQueue(capacity=int(os.environ["EVENT_QUEUE_CAPACITY"]))
    store = EventStore(capacity=int(os.environ["EVENT_STORE_CAPACITY"]))
    broadcaster = EventBroadcaster(capacity=int(os.environ["SSE_QUEUE_CAPACITY"]))
    stream = EventStream(store, store, broadcaster, broadcaster)
    model = create_chat_model(os.environ)
    processor = EventProcessor(queue, LlmScorer(model), stream)
    log_path = Path(os.environ["ATTACK_LOG_PATH"])
    if not log_path.is_absolute():
        log_path = bridge_path / log_path

    async with httpx.AsyncClient() as client:
        poller = LegacyApiPoller(
            client,
            queue.put,
            url=os.environ["LEGACYCORE_ENDPOINT"],
            interval_seconds=float(os.environ["LEGACY_POLL_INTERVAL_SECONDS"]),
            timeout_seconds=float(os.environ["LEGACY_REQUEST_TIMEOUT_SECONDS"]),
            dedup_capacity=int(os.environ["LEGACY_DEDUP_CAPACITY"]),
        )
        watcher = AttackLogWatcher(
            queue.put,
            log_path=log_path,
            retry_interval_seconds=float(os.environ["ATTACK_WATCH_RETRY_SECONDS"]),
        )
        logger.info("Starting both readers and event processor with LLM scoring and in-memory history")
        async with asyncio.TaskGroup() as tasks:
            workers = [
                tasks.create_task(poller.run(), name="legacy-api-poller"),
                tasks.create_task(watcher.run(), name="attack-log-watcher"),
                tasks.create_task(processor.run(), name="event-processor"),
            ]
            try:
                yield stream
            finally:
                broadcaster.close()
                for worker in workers:
                    worker.cancel()


async def main() -> None:
    async with bridge_runtime():
        await asyncio.Event().wait()


if __name__ == "__main__":
    import uvicorn

    from api.app import create_app

    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_environment()
    uvicorn.run(
        create_app(), host=os.environ["API_HOST"], port=int(os.environ["API_PORT"]),
        workers=1, timeout_graceful_shutdown=5,
    )