import asyncio

from models import ProcessedEvent

from .exceptions import StreamClosed


class StreamSubscription:
    def __init__(self, capacity: int) -> None:
        self._queue: asyncio.Queue[ProcessedEvent | None] = asyncio.Queue(maxsize=capacity)
        self._closed = False

    def offer(self, event: ProcessedEvent) -> bool:
        if self._closed:
            return False
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.close()
            return False
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)

    async def receive(self) -> ProcessedEvent:
        if self._closed:
            raise StreamClosed
        event = await self._queue.get()
        if event is None:
            raise StreamClosed
        return event