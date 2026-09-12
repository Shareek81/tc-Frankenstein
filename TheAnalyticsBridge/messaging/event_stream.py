from collections.abc import Iterator
from contextlib import contextmanager

from models import ProcessedEvent
from processing.contracts import EventReader, EventWriter

from .contracts import EventPublisher, EventSubscriptions
from .stream_connection import StreamConnection


class EventStream:
    """Coordinate synchronous store and fan-out operations on one event loop."""

    def __init__(
        self, reader: EventReader, writer: EventWriter,
        publisher: EventPublisher, subscriptions: EventSubscriptions,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._publisher = publisher
        self._subscriptions = subscriptions

    def append(self, event: ProcessedEvent) -> None:
        self._writer.append(event)
        self._publisher.publish(event)

    def snapshot(self) -> tuple[ProcessedEvent, ...]:
        return self._reader.snapshot()

    @contextmanager
    def connect(self) -> Iterator[StreamConnection]:
        with self._subscriptions.subscribe() as subscription:
            yield StreamConnection(self._reader.snapshot(), subscription)