"""Runs the learning cycle at 11 pm: it waits while a consultation is being
recorded (and for 10 quiet minutes after), and catches up later the same
night if the Mac was asleep or the app closed at 11 pm. It never starts
between 7 am and 11 pm, so clinic hours are never slowed."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import logging
import threading
import time

logger = logging.getLogger(__name__)

RUN_AT_HOUR = 23
NIGHT_ENDS_HOUR = 7
QUIET_SECONDS = 600

_lock = threading.Lock()
_in_progress = 0
_last_activity = 0.0
_running = threading.Lock()
_started = False


@contextmanager
def consultation_in_progress():
    global _in_progress, _last_activity
    with _lock:
        _in_progress += 1
    try:
        yield
    finally:
        with _lock:
            _in_progress -= 1
            _last_activity = time.monotonic()


def clinic_is_busy() -> bool:
    with _lock:
        return _in_progress > 0 or (_last_activity and time.monotonic() - _last_activity < QUIET_SECONDS)


def due(last_run: datetime, now: datetime) -> bool:
    """True at night once the most recent 11 pm has passed without a run."""

    if NIGHT_ENDS_HOUR <= now.hour < RUN_AT_HOUR:
        return False
    latest = now.replace(hour=RUN_AT_HOUR, minute=0, second=0, microsecond=0)
    if now < latest:
        latest -= timedelta(days=1)
    return last_run < latest


def run_now(reason: str) -> dict | None:
    """One cycle at a time; returns the report, or None if one is running."""

    from .cycle import run_cycle

    if not _running.acquire(blocking=False):
        return None
    try:
        return run_cycle(reason=reason)
    finally:
        _running.release()


def is_running() -> bool:
    return _running.locked()


def _loop() -> None:
    from .cycle import cycle_level, last_run_time

    # Before the first report, count from when the app was first started.
    first_seen = datetime.now()
    while True:
        time.sleep(60)
        try:
            if cycle_level() != "disabled" and due(last_run_time() or first_seen, datetime.now()) and not clinic_is_busy():
                run_now("scheduled")
        except Exception:
            logger.exception("Learning cycle failed")


def start_scheduler() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="learning-cycle", daemon=True).start()
