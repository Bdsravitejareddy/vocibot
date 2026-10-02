"""A dedicated worker for one consultation's local CPU inference."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable


class LocalPipelineExecutor:
    """Keep warm-up and live ASR on the same thread-local model context."""

    def __init__(self, *, workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, workers),
            thread_name_prefix="vocibot-live-asr",
        )

    async def run(self, operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, partial(operation, *args, **kwargs))

    def close(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)
