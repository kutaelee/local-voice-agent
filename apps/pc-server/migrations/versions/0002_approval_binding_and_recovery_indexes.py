"""Persist approval preconditions and recovery lookup indexes.

Revision ID: 0002_approval_recovery
Revises: 0001_initial
Create Date: 2026-07-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_approval_recovery"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approval_requests",
        sa.Column(
            "precondition_version",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_tool_executions_state_updated",
        "tool_executions",
        ["state", "updated_at"],
    )
    op.create_index(
        "ix_approval_requests_pending_expires",
        "approval_requests",
        ["state", "expires_at"],
        postgresql_where=sa.text("state = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_approval_requests_pending_expires", table_name="approval_requests")
    op.drop_index("ix_tool_executions_state_updated", table_name="tool_executions")
    op.drop_column("approval_requests", "precondition_version")
