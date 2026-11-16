"""Initial engine schema: sessions, turns, audit events, feedback, appointment requests and contacts.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("demo_mode", sa.Boolean(), nullable=False),
        sa.Column("turns_used", sa.Integer(), nullable=False),
        sa.Column("strikes", sa.Integer(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_turn_id", sa.String(64), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("language", sa.String(2), nullable=True),
        sa.Column("risk_kinds", sa.JSON(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=True),
        sa.Column("classifier", sa.String(16), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("degraded", sa.JSON(), nullable=False),
        sa.Column("latencies_ms", sa.JSON(), nullable=False),
        sa.Column("total_ms", sa.Float(), nullable=True),
        sa.Column("redactions", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("app_version", sa.String(32), nullable=False),
        sa.Column("corpus_version", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(32), nullable=False),
        sa.Column("models", sa.JSON(), nullable=False),
    )
    op.create_index("ix_turns_session", "turns", ["session_id"])
    op.create_index("ix_turns_created", "turns", ["created_at"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("turn_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    op.create_index("ix_audit_created", "audit_events", ["created_at"])
    op.create_index("ix_audit_type", "audit_events", ["event_type"])
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(16), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_table(
        "appointment_requests",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("department_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("purge_after", _TS, nullable=False),
    )
    op.create_table(
        "appointment_contacts",
        sa.Column(
            "request_id",
            sa.String(16),
            sa.ForeignKey("appointment_requests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("preferred_dates", sa.String(300), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("purge_after", _TS, nullable=False),
    )
    op.create_index("ix_contacts_purge", "appointment_contacts", ["purge_after"])


def downgrade() -> None:
    op.drop_index("ix_contacts_purge", table_name="appointment_contacts")
    op.drop_table("appointment_contacts")
    op.drop_table("appointment_requests")
    op.drop_table("feedback")
    op.drop_index("ix_audit_type", table_name="audit_events")
    op.drop_index("ix_audit_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_turns_created", table_name="turns")
    op.drop_index("ix_turns_session", table_name="turns")
    op.drop_table("turns")
    op.drop_table("sessions")
