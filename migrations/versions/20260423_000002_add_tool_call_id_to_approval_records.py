"""add tool_call_id to approval records

Revision ID: 20260423_000002
Revises: 20260422_000001
Create Date: 2026-04-23 15:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_000002"
down_revision = "20260422_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approval_records",
        sa.Column("tool_call_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approval_records", "tool_call_id")
