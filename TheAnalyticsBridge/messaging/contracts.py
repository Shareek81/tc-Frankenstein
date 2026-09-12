from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Protocol

from models import ProcessedEvent

if TYPE_CHECKING:
    from .stream_connection import StreamConnection


class EventSubscription(Protocol):
    async def receive(self) -> ProcessedEvent: ...


class EventPublisher(Protocol):
    def publish(self, event: ProcessedEvent) -> None: ...


class EventSubscriptions(Protocol):
    def subscribe(self) -> AbstractContextManager[EventSubscription]: ...


class EventFeed(Protocol):
    def connect(self) -> AbstractContextManager["StreamConnection"]: ...