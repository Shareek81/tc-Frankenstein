import asyncio
import json
import logging
import os
from pathlib import Path

import httpx

from configuration import load_environment
from ingestion.attack_log_watcher import AttackLogWatcher
from ingestion.legacy_api_poller import LegacyApiPoller
from integrations import LlmScorer
from integrations.model_strategies import create_chat_model
from messaging.event_queue import EventQueue
from processing import EventProcessor, EventReader
from storage import EventStore


logger = logging.getLogger(__name__)


async def print_event_store(store: EventReader) -> None:
    previous_snapshot = None
    while True:
        snapshot = store.snapshot()
        if snapshot != previous_snapshot:
            print(
                json.dumps({"event_store": [event.to_payload() for event in snapshot]}, indent=2),
                flush=True,
            )
            previous_snapshot = snapshot
        await asyncio.sleep(1)


async def main() -> None:
    bridge_path = load_environment()
    queue = EventQueue(capacity=int(os.environ["EVENT_QUEUE_CAPACITY"]))
    store = EventStore(capacity=int(os.environ["EVENT_STORE_CAPACITY"]))
    model = create_chat_model(os.environ)
    processor = EventProcessor(queue, LlmScorer(model), store)
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
            tasks.create_task(poller.run(), name="legacy-api-poller")
            tasks.create_task(watcher.run(), name="attack-log-watcher")
            tasks.create_task(processor.run(), name="event-processor")
            tasks.create_task(print_event_store(store), name="event-store-printer")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass