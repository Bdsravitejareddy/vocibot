from datetime import datetime, timezone
import secrets
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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


class User(Base):
    """A clinic account. Admins manage accounts; every user sees only their own patients."""

    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # Stored lower-case: usernames are case-insensitive.
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="clinician")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    """A signed-in browser. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user: Mapped[User] = relationship()


class SecurityEvent(Base):
    """Append-only log of sign-ins and account and record administration."""

    __tablename__ = "security_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    event: Mapped[str] = mapped_column(String(60), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    subject_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("owner_id", "patient_identifier", name="uq_patients_owner_identifier"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    patient_identifier: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    age: Mapped[int] = mapped_column(Integer)
    sex: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consultations: Mapped[list["Consultation"]] = relationship(back_populates="patient")


class Consultation(Base):
    __tablename__ = "consultations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=new_session_code)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="IN_PROGRESS", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Background processing after Stop: idle, queued, transcribing, writing_note, done, failed.
    processing_status: Mapped[str] = mapped_column(String(20), default="idle", index=True)
    # Planned stages, comma separated: "transcribe,note" or "note".
    processing_plan: Mapped[str] = mapped_column(String(40), default="")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_warnings: Mapped[list] = mapped_column(JSON, default=list)
    processing_queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    patient: Mapped[Patient] = relationship(back_populates="consultations")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(back_populates="consultation", cascade="all, delete-orphan")
    clinical_record: Mapped["ClinicalRecord"] = relationship(back_populates="consultation", uselist=False, cascade="all, delete-orphan")
    updates: Mapped[list["RecordUpdate"]] = relationship(back_populates="consultation", cascade="all, delete-orphan")
    recordings: Mapped[list["Recording"]] = relationship(back_populates="consultation", cascade="all, delete-orphan", order_by="Recording.started_at")


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
    # Who made the change (None for AI updates); clinical audit trail.
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    consultation: Mapped[Consultation] = relationship(back_populates="updates")
