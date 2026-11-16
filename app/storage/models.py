"""Relational schema (SQLAlchemy 2, async). NO message text is stored anywhere in it.

Personal data exists only in `appointment_contacts` (separate table, 30-day retention, purge_expired()) and, after
deterministic redaction, in optional feedback comments.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str] = mapped_column(String(2))
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    turns_used: Mapped[int] = mapped_column(Integer, default=0)
    strikes: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class TurnRow(Base):
    __tablename__ = "turns"
    __table_args__ = (Index("ix_turns_session", "session_id"), Index("ix_turns_created", "created_at"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"))
    client_turn_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(2), nullable=True)
    risk_kinds: Mapped[list[str]] = mapped_column(JSON, default=list)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    classifier: Mapped[str] = mapped_column(String(16), default="none")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    degraded: Mapped[list[str]] = mapped_column(JSON, default=list)
    latencies_ms: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    redactions: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    app_version: Mapped[str] = mapped_column(String(32))
    corpus_version: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(32))
    models: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_created", "created_at"), Index("ix_audit_type", "event_type"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(48))
    detail: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class FeedbackRow(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[str] = mapped_column(String(36))
    turn_id: Mapped[str] = mapped_column(String(36))
    rating: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)  # redacted before storage


class AppointmentRequestRow(Base):
    __tablename__ = "appointment_requests"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # short code shown to the user
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[str] = mapped_column(String(36))
    department_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="new")
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppointmentContactRow(Base):
    """Personal data of an appointment request, kept apart so it can be purged and access-controlled."""

    __tablename__ = "appointment_contacts"
    __table_args__ = (Index("ix_contacts_purge", "purge_after"),)

    request_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("appointment_requests.id", ondelete="CASCADE"), primary_key=True
    )
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    preferred_dates: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
