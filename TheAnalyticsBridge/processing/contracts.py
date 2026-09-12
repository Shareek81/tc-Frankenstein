from typing import Protocol

from models import ILog
from models.event_assessment import EventAssessment
from models.processed_event import ProcessedEvent


class EventSource(Protocol):
    async def get(self) -> ILog: ...

    def task_done(self) -> None: ...


class EventScorer(Protocol):
    @property
    def name(self) -> str: ...

    async def score(self, log: ILog) -> EventAssessment: ...


class EventWriter(Protocol):
    def append(self, event: ProcessedEvent) -> None: ...


class EventReader(Protocol):
    def snapshot(self) -> tuple[ProcessedEvent, ...]: ...