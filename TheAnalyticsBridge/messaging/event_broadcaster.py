from collections.abc import Iterator
from contextlib import contextmanager

from models import ProcessedEvent

from .exceptions import StreamClosed
from .stream_subscription import StreamSubscription


class EventBroadcaster:
    def __init__(self, *, capacity: int) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Subscriber queue capacity must be a positive integer")
        self._capacity = capacity
        self._subscribers: set[StreamSubscription] = set()
        self._closed = False

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @contextmanager
    def subscribe(self) -> Iterator[StreamSubscription]:
        if self._closed:
            raise StreamClosed
        subscription = StreamSubscription(self._capacity)
        self._subscribers.add(subscription)
        try:
            yield subscription
        finally:
            self._subscribers.discard(subscription)
            subscription.close()

    def publish(self, event: ProcessedEvent) -> None:
        for subscription in tuple(self._subscribers):
            if not subscription.offer(event):
                self._subscribers.discard(subscription)

    def close(self) -> None:
        self._closed = True
        for subscription in self._subscribers:
            subscription.close()
        self._subscribers.clear()