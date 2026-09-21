"""
Unit tests for JobSemaphore (Phase 10).

Tests verify:
  - max_parallel=1  : second task blocks until first completes
  - max_parallel=None: unlimited  tasks run without blocking each other
  - max_parallel=2  : third task waits while the first two run concurrently
  - semaphore_wait event is logged when a task must wait
"""
import asyncio
from unittest.mock import call, patch, MagicMock

import pytest

from app.semaphore import JobSemaphore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_with_semaphore(
    sem: JobSemaphore,
    db_name: str,
    results: list,
    delay: float = 0.05,
) -> None:
    """Acquire semaphore, record start, sleep briefly, record finish, release."""
    await sem.acquire(database=db_name)
    try:
        results.append(f"start:{db_name}")
        await asyncio.sleep(delay)
        results.append(f"end:{db_name}")
    finally:
        await sem.release()


# ---------------------------------------------------------------------------
# max_parallel = 1  (strict serialisation)
# ---------------------------------------------------------------------------

class TestMaxParallelOne:
    @pytest.mark.asyncio
    async def test_second_task_starts_after_first_ends(self):
        """
        With max_parallel=1, the two tasks must not interleave.
        Expected order: start:A, end:A, start:B, end:B
        """
        sem = JobSemaphore(max_parallel=1)
        results: list[str] = []

        await asyncio.gather(
            _run_with_semaphore(sem, "db_a", results, delay=0.05),
            _run_with_semaphore(sem, "db_b", results, delay=0.05),
        )

        # Interleaving would look like: start:A, start:B, end:A, end:B
        # We must see both ends after both starts in strict pairs
        assert results.index("end:db_a") < results.index("start:db_b") or \
               results.index("end:db_b") < results.index("start:db_a"), \
               f"Tasks interleaved with max_parallel=1: {results}"

    @pytest.mark.asyncio
    async def test_all_tasks_complete(self):
        sem = JobSemaphore(max_parallel=1)
        results: list[str] = []

        await asyncio.gather(
            _run_with_semaphore(sem, "db_a", results),
            _run_with_semaphore(sem, "db_b", results),
            _run_with_semaphore(sem, "db_c", results),
        )

        assert results.count("start:db_a") == 1
        assert results.count("start:db_b") == 1
        assert results.count("start:db_c") == 1
        assert len(results) == 6  # 3 starts + 3 ends


# ---------------------------------------------------------------------------
# max_parallel = None  (unlimited)
# ---------------------------------------------------------------------------

class TestMaxParallelUnlimited:
    @pytest.mark.asyncio
    async def test_tasks_run_concurrently(self):
        """
        With no limit (None), all tasks should start before any ends
        when given a long enough delay.
        """
        sem = JobSemaphore(max_parallel=None)
        results: list[str] = []

        await asyncio.gather(
            _run_with_semaphore(sem, "db_a", results, delay=0.1),
            _run_with_semaphore(sem, "db_b", results, delay=0.1),
            _run_with_semaphore(sem, "db_c", results, delay=0.1),
        )

        # All starts should appear before all ends
        start_indices = [i for i, r in enumerate(results) if r.startswith("start:")]
        end_indices = [i for i, r in enumerate(results) if r.startswith("end:")]
        assert max(start_indices) < min(end_indices), \
            f"Unlimited semaphore did not allow concurrent execution: {results}"

    @pytest.mark.asyncio
    async def test_all_tasks_complete(self):
        sem = JobSemaphore(max_parallel=None)
        results: list[str] = []

        await asyncio.gather(
            _run_with_semaphore(sem, "db_a", results),
            _run_with_semaphore(sem, "db_b", results),
        )

        assert len(results) == 4


# ---------------------------------------------------------------------------
# max_parallel = 2  (two run, third waits)
# ---------------------------------------------------------------------------

class TestMaxParallelTwo:
    @pytest.mark.asyncio
    async def test_third_task_waits_for_first_slot(self):
        """
        With max_parallel=2, three tasks: the third must wait until one finishes.
        Verify that at no point three tasks are running simultaneously.
        """
        sem = JobSemaphore(max_parallel=2)
        active = [0]
        max_active = [0]

        async def _track(db_name: str) -> None:
            await sem.acquire(database=db_name)
            try:
                active[0] += 1
                max_active[0] = max(max_active[0], active[0])
                await asyncio.sleep(0.05)
            finally:
                active[0] -= 1
                await sem.release()

        await asyncio.gather(_track("a"), _track("b"), _track("c"))

        assert max_active[0] <= 2, \
            f"max_parallel=2 was violated: {max_active[0]} tasks ran simultaneously"

    @pytest.mark.asyncio
    async def test_all_complete_with_max_parallel_two(self):
        sem = JobSemaphore(max_parallel=2)
        results: list[str] = []

        await asyncio.gather(
            _run_with_semaphore(sem, "db_a", results),
            _run_with_semaphore(sem, "db_b", results),
            _run_with_semaphore(sem, "db_c", results),
        )

        assert len(results) == 6


# ---------------------------------------------------------------------------
# semaphore_wait log event
# ---------------------------------------------------------------------------

class TestSemaphoreWaitLog:
    @pytest.mark.asyncio
    async def test_semaphore_wait_event_logged_when_blocking(self):
        """
        When a second task must wait (max_parallel=1 and first task holds the slot),
        the `semaphore_wait` log event must be emitted before the second task acquires.
        """
        sem = JobSemaphore(max_parallel=1)

        log_events: list[str] = []

        original_info = None

        with patch("app.semaphore.log") as mock_log:
            # First acquire  should not log (slot available)
            await sem.acquire(database="db_a")

            # Second acquire  slot is taken, must log semaphore_wait
            # We do this in a separate task so the event loop can schedule it
            async def _wait_task() -> None:
                await sem.acquire(database="db_b")
                await sem.release()

            wait_task = asyncio.create_task(_wait_task())
            # Yield control so wait_task can start and hit the blocked path
            await asyncio.sleep(0)

            # At this point wait_task should have seen _value==0 and logged
            mock_log.info.assert_called_once_with(
                "semaphore_wait",
                "Waiting for a semaphore slot (max_parallel reached)",
                database="db_b",
                max_parallel=1,
            )

            # Release first slot so wait_task can complete
            await sem.release()
            await wait_task

    @pytest.mark.asyncio
    async def test_semaphore_wait_not_logged_when_slot_available(self):
        """With a free slot, semaphore_wait must NOT be logged."""
        sem = JobSemaphore(max_parallel=2)

        with patch("app.semaphore.log") as mock_log:
            await sem.acquire(database="db_a")
            mock_log.info.assert_not_called()
            await sem.release()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_acquires_and_releases(self):
        sem = JobSemaphore(max_parallel=1)

        async with sem:
            # We're inside  semaphore is held, value should be 0
            assert sem._sem._value == 0

        # After exiting  slot is released
        assert sem._sem._value == 1

    @pytest.mark.asyncio
    async def test_context_manager_releases_on_exception(self):
        sem = JobSemaphore(max_parallel=1)

        with pytest.raises(ValueError):
            async with sem:
                raise ValueError("oops")

        # Slot must be released even after exception
        assert sem._sem._value == 1
