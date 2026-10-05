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


def test_live_preview_gets_the_gpu_before_final_pass_work(monkeypatch) -> None:
    import threading
    import time

    from app.config import settings
    from app.providers.speech import _GpuLock

    monkeypatch.setattr(settings, "live_gpu_priority", True)
    lock, order = _GpuLock(), []
    holding, release = threading.Event(), threading.Event()

    def run(name: str, live: bool, hold: bool = False) -> None:
        lock.live(live)
        with lock:
            if hold:
                holding.set()
                release.wait(2)
            order.append(name)

    first = threading.Thread(target=run, args=("final piece in progress", False, True))
    first.start()
    holding.wait(2)
    waiting_live = threading.Thread(target=run, args=("live", True))
    waiting_live.start()
    time.sleep(0.1)
    waiting_final = threading.Thread(target=run, args=("next final piece", False))
    waiting_final.start()
    time.sleep(0.1)
    release.set()
    for thread in (first, waiting_live, waiting_final):
        thread.join(2)
    assert order == ["final piece in progress", "live", "next final piece"]
