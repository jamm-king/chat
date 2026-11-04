import asyncio
from collections.abc import Awaitable, Callable


class AsyncioJobExecutor:
    """Single-process execution. A timed-out thread may finish; publication is gated by the use case."""

    def __init__(self):
        self.tasks: set[asyncio.Task] = set()

    async def start(self, work: Callable[[], Awaitable[None]]) -> None:
        task = asyncio.create_task(work())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def shutdown(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def call(self, function, *args, timeout=None):
        work = asyncio.to_thread(function, *args)
        if timeout is None:
            return await work
        return await asyncio.wait_for(work, timeout=timeout)
