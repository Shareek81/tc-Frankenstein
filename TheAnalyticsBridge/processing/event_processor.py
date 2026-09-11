from datetime import datetime, timezone
from uuid import uuid4

from models.processed_event import ProcessedEvent

from .contracts import EventScorer, EventSource, EventWriter


class EventProcessor:
    def __init__(self, source: EventSource, scorer: EventScorer, store: EventWriter) -> None:
        self._source = source
        self._scorer = scorer
        self._store = store

    async def process_once(self) -> ProcessedEvent:
        log = await self._source.get()
        try:
            score = await self._scorer.score(log)
            event = ProcessedEvent(
                event_id=str(uuid4()),
                log=log,
                danger_score=score,
                scoring_method=self._scorer.name,
                processed_at=datetime.now(timezone.utc),
            )
            self._store.append(event)
            return event
        finally:
            self._source.task_done()

    async def run(self) -> None:
        while True:
            await self.process_once()