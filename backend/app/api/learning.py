"""Nightly learning: preferences, Gemini key status, reports and the log of
everything sent to Gemini."""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..learning import cycle, scheduler
from ..learning.gemini import keychain_keys
from ..learning.tips import active

router = APIRouter(prefix="/api/learning", tags=["learning"])


class LearningPreferences(BaseModel):
    enabled: bool | None = None
    cloud_level: str | None = None


def _status() -> dict:
    latest = cycle.reports(1)
    return {"enabled": cycle.learning_enabled(), "cloud_level": cycle.cloud_level(), "levels": list(cycle.LEVELS),
            "gemini_keys": len(keychain_keys()), "running": scheduler.is_running(), "active_tips": active(),
            "last_report": latest[0] if latest else None}


@router.get("")
def get_learning() -> dict:
    return _status()


@router.put("")
def put_learning(payload: LearningPreferences) -> dict:
    try:
        cycle.set_preferences(enabled=payload.enabled, level=payload.cloud_level)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _status()


@router.post("/run")
def run_learning() -> dict:
    if scheduler.clinic_is_busy():
        raise HTTPException(status_code=409, detail="A consultation is in progress or just finished; try again in 10 minutes.")
    if scheduler.is_running():
        raise HTTPException(status_code=409, detail="A learning cycle is already running.")
    threading.Thread(target=scheduler.run_now, args=("run now",), name="learning-run-now", daemon=True).start()
    return {"started": True}


@router.get("/reports")
def get_reports(limit: int = 20) -> list[dict]:
    return [{key: value for key, value in report.items() if key != "trace"} for report in cycle.reports(limit)]


@router.get("/audit")
def get_audit(limit: int = 200) -> list[dict]:
    return cycle.audit(limit)
