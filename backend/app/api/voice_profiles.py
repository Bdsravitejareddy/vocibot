"""Doctor voice enrolment: record a few sentences once; only the voice
fingerprint is kept (the recordings are not stored)."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..models import AppSetting
from ..providers.audio import decode_audio_payload
from ..services.voice_profile import MIN_SECONDS, PROFILES_KEY, VoiceEncoder, build_profile, stored_profiles

router = APIRouter(prefix="/api/voice-profiles", tags=["voice profiles"])
KEY = PROFILES_KEY


class Enrolment(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sample_rate: int = Field(ge=8_000, le=96_000)
    # Base64 little-endian float32 mono PCM, one per sentence read.
    samples: list[str] = Field(min_length=1, max_length=20)


def _save(session: Session, profiles: list[dict]) -> None:
    row = session.get(AppSetting, KEY)
    if row is None:
        session.add(AppSetting(key=KEY, value=profiles))
    else:
        row.value = profiles
    session.commit()


def _public(profile: dict) -> dict:
    return {key: profile[key] for key in ("id", "name", "samples", "created_at", "threshold")}


def encoder() -> VoiceEncoder:
    model = VoiceEncoder(settings.voice_model_dir)
    if not settings.voice_model_dir or not model.available():
        raise HTTPException(status_code=503, detail="The voice model is not installed on this computer.")
    return model


@router.get("")
def list_profiles(session: Session = Depends(get_session)) -> dict:
    available = bool(settings.voice_model_dir) and VoiceEncoder(settings.voice_model_dir).available()
    return {"available": available, "profiles": [_public(profile) for profile in stored_profiles(session)]}


@router.post("")
def enrol(payload: Enrolment, session: Session = Depends(get_session)) -> dict:
    model = encoder()
    fingerprints, too_short = [], []
    for index, sample in enumerate(payload.samples):
        try:
            audio = decode_audio_payload(base64.b64decode(sample), encoding="pcm_f32le", sample_rate=payload.sample_rate, channels=1).waveform
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"Sentence {index + 1} could not be read: {error}") from error
        audio = model.speech_only(audio)
        if len(audio) < MIN_SECONDS * 16_000:
            too_short.append(index + 1)
            continue
        fingerprints.append(model.embed(audio))
    if too_short:
        raise HTTPException(status_code=422, detail=f"Sentence {', '.join(map(str, too_short))} was too short; record it again.")
    try:
        built = build_profile(fingerprints)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if built["outliers"]:
        sentences = ", ".join(str(index + 1) for index in built["outliers"])
        raise HTTPException(status_code=422, detail=f"Sentence {sentences} does not sound like the others (background noise or another voice?); record it again.")
    profile = {"id": str(uuid.uuid4()), "name": payload.name.strip(), "samples": len(fingerprints), "created_at": datetime.now(timezone.utc).isoformat(), "embedding": built["embedding"], "threshold": built["threshold"]}
    _save(session, [*stored_profiles(session), profile])
    return _public(profile)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: str, session: Session = Depends(get_session)) -> None:
    profiles = stored_profiles(session)
    remaining = [profile for profile in profiles if profile["id"] != profile_id]
    if len(remaining) == len(profiles):
        raise HTTPException(status_code=404, detail="voice profile not found")
    _save(session, remaining)
