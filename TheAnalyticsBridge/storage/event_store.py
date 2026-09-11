from collections import deque

from models.processed_event import ProcessedEvent


class EventStore:
    def __init__(self, *, capacity: int) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Store capacity must be a positive integer")
        self._events: deque[ProcessedEvent] = deque(maxlen=capacity)

    def append(self, event: ProcessedEvent) -> None:
        self._events.append(event)

    def snapshot(self) -> tuple[ProcessedEvent, ...]:
        return tuple(self._events)