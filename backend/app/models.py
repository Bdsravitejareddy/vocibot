from datetime import datetime, timezone
import secrets
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Crockford-style alphabet: no I, L, O or U, so codes read aloud unambiguously.
SESSION_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_session_code(when: datetime | None = None) -> str:
    """A human-readable unique session ID, e.g. VB-20261002-K7Q3MD."""

    stamp = (when or utcnow()).strftime("%Y%m%d")
    return f"VB-{stamp}-" + "".join(secrets.choice(SESSION_CODE_ALPHABET) for _ in range(6))


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_identifier: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    age: Mapped[int] = mapped_column(Integer)
    sex: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consultations: Mapped[list["Consultation"]] = relationship(back_populates="patient")


class Consultation(Base):
    __tablename__ = "consultations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=new_session_code)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="IN_PROGRESS", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    patient: Mapped[Patient] = relationship(back_populates="consultations")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(back_populates="consultation", cascade="all, delete-orphan")
    clinical_record: Mapped["ClinicalRecord"] = relationship(back_populates="consultation", uselist=False, cascade="all, delete-orphan")
    updates: Mapped[list["RecordUpdate"]] = relationship(back_populates="consultation", cascade="all, delete-orphan")
    recordings: Mapped[list["Recording"]] = relationship(back_populates="consultation", cascade="all, delete-orphan", order_by="Recording.started_at")
    translation_segments: Mapped[list["TranslationSegment"]] = relationship(cascade="all, delete-orphan", order_by="TranslationSegment.sequence_number")


class Recording(Base):
    """One captured audio stream of a consultation, kept for compliance and re-analysis."""

    __tablename__ = "recordings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    sample_rate: Mapped[int] = mapped_column(Integer)
    language_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # SHA-256 of the file as stored now: proves it was not altered.
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # SHA-256 of the original capture (WAV); kept through every conversion.
    original_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    format: Mapped[str] = mapped_column(String(10), default="wav")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    consultation: Mapped[Consultation] = relationship(back_populates="recordings")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("consultation_id", "id", name="uq_segment_consultation_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), index=True)
    speaker: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    language_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Consultation-relative audio time, formatted as HH:MM:SS. This is deliberately
    # not a wall-clock datetime so persisted transcripts cannot leak system time.
    timestamp: Mapped[str] = mapped_column(String(12))
    sequence_number: Mapped[int] = mapped_column(Integer)
    consultation: Mapped[Consultation] = relationship(back_populates="transcript_segments")


class ClinicalRecord(Base):
    __tablename__ = "clinical_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), unique=True, index=True)
    structured_data_json: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    consultation: Mapped[Consultation] = relationship(back_populates="clinical_record")


class RecordUpdate(Base):
    __tablename__ = "record_updates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(100))
    previous_value: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    source_transcript_segment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_type: Mapped[str] = mapped_column(String(40))
    consultation: Mapped[Consultation] = relationship(back_populates="updates")


class AppSetting(Base):
    """Small app-wide preferences (e.g. enabled languages), stored as JSON."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)


class TranslationSegment(Base):
    """English translation of a non-English consultation, made from the audio.

    The clinical note is written from (and evidence-checked against) these
    segments; the original-language transcript stays the record.
    """

    __tablename__ = "translation_segments"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    # DOCTOR / PATIENT recognised from the content (services/speaker_roles.py).
    speaker: Mapped[str] = mapped_column(String(30), default="UNKNOWN", server_default="UNKNOWN")
    timestamp: Mapped[str] = mapped_column(String(40))
    sequence_number: Mapped[int] = mapped_column(Integer)
