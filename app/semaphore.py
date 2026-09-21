import asyncio
from typing import Optional

from app.logger import log


class JobSemaphore:
    """
    Wraps asyncio.Semaphore with logging and a configurable concurrency cap.

    When max_parallel is None the semaphore is initialised with 9999 slots —
    effectively unlimited  so no code path needs a special "no-semaphore" branch.

    Usage:
        # Explicit acquire/release (scheduler queue worker):
        await semaphore.acquire(database="my_db")
        try:
            await run_backup()
        finally:
            await semaphore.release()

        # Context manager:
        async with semaphore:
            await run_backup()
    """

    _UNLIMITED = 9999

    def __init__(self, max_parallel: Optional[int] = None) -> None:
        limit = max_parallel if max_parallel is not None else self._UNLIMITED
        self._sem = asyncio.Semaphore(limit)
        self._limit = limit

    async def acquire(self, database: str = "") -> None:
        """
        Acquire a semaphore slot.
        Logs a `semaphore_wait` event before blocking if no slot is immediately available.
        """
        if self._sem._value == 0:
            log.info(
                "semaphore_wait",
                "Waiting for a semaphore slot (max_parallel reached)",
                database=database,
                max_parallel=self._limit,
            )
        await self._sem.acquire()

    async def release(self) -> None:
        """Release the held semaphore slot."""
        self._sem.release()

    async def __aenter__(self) -> "JobSemaphore":
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.release()
