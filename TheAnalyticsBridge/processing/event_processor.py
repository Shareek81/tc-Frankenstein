import logging
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
            try:
                assessment = await self._scorer.score(log)
            except Exception:
                logging.getLogger(__name__).warning("AI assessment failed; retaining event without AI results")
                assessment = None
            event = ProcessedEvent(
                event_id=str(uuid4()),
                log=log,
                danger_score=assessment.danger_score if assessment else None,
                scoring_method=self._scorer.name if assessment else "unavailable",
                processed_at=datetime.now(timezone.utc),
                insight=assessment.insight if assessment else (),
                respondsuggested=assessment.respondsuggested if assessment else (),
            )
            self._store.append(event)
            return event
        finally:
            self._source.task_done()

    async def run(self) -> None:
        while True:
            await self.process_once()