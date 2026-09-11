import asyncio

from models import ILog


class EventQueue:
    def __init__(self, *, capacity: int) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Queue capacity must be a positive integer")
        self._queue: asyncio.Queue[ILog] = asyncio.Queue(maxsize=capacity)

    async def put(self, event: ILog) -> None:
        await self._queue.put(event)

    async def get(self) -> ILog:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def qsize(self) -> int:
        return self._queue.qsize()