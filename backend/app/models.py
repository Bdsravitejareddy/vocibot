from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="IN_PROGRESS", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    patient: Mapped[Patient] = relationship(back_populates="consultations")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(back_populates="consultation", cascade="all, delete-orphan")
    clinical_record: Mapped["ClinicalRecord"] = relationship(back_populates="consultation", uselist=False, cascade="all, delete-orphan")
    updates: Mapped[list["RecordUpdate"]] = relationship(back_populates="consultation", cascade="all, delete-orphan")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("consultation_id", "id", name="uq_segment_consultation_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), index=True)
    speaker: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
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
