from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_session
from ..languages import LANGUAGES, enabled_languages, set_enabled_languages

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LanguageSelection(BaseModel):
    enabled: list[str]


def _languages(session: Session) -> dict:
    return {"enabled": enabled_languages(session), "available": [{"code": code, "name": name} for code, name in LANGUAGES]}


@router.get("/languages")
def get_languages(session: Session = Depends(get_session)) -> dict:
    return _languages(session)


@router.put("/languages")
def put_languages(payload: LanguageSelection, session: Session = Depends(get_session)) -> dict:
    try:
        set_enabled_languages(session, payload.enabled)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _languages(session)
