import asyncio
import threading
import time

from app.services.live_cpu import LocalPipelineExecutor


def test_local_pipeline_executor_reuses_one_worker_for_warmup_and_live_inference() -> None:
    async def run() -> tuple[int, int]:
        executor = LocalPipelineExecutor()
        try:
            return await executor.run(threading.get_ident), await executor.run(threading.get_ident)
        finally:
            executor.close()

    warmup_thread, inference_thread = asyncio.run(run())

    assert warmup_thread == inference_thread


def test_local_pipeline_executor_uses_configured_parallel_workers() -> None:
    def blocking_operation() -> int:
        time.sleep(0.06)
        return threading.get_ident()

    async def run() -> tuple[float, set[int]]:
        executor = LocalPipelineExecutor(workers=2)
        try:
            started = time.perf_counter()
            worker_ids = await asyncio.gather(
                executor.run(blocking_operation),
                executor.run(blocking_operation),
            )
            return time.perf_counter() - started, set(worker_ids)
        finally:
            executor.close()

    elapsed, worker_ids = asyncio.run(run())

    assert elapsed < 0.11
    assert len(worker_ids) == 2
