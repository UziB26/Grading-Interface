"""Helpers for running coroutines from synchronous Flask request handlers."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import TypeVar

T = TypeVar("T")

# Dedicated thread avoids nested-event-loop failures when a loop is already running.
_ASYNC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="grading-async",
)


def run_async(coro: Coroutine[object, object, T]) -> T:
    """Run a coroutine from sync code, including under an active event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    future = _ASYNC_EXECUTOR.submit(asyncio.run, coro)
    return future.result()
