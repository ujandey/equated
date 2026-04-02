"""add student model tables

Revision ID: c13a5f8b7d21
Revises: 9f3a7d2b1c4e
Create Date: 2026-04-03 12:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c13a5f8b7d21"
down_revision: Union[str, Sequence[str], None] = "9f3a7d2b1c4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_topic_mastery",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("subject", sa.String(length=50), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("mastery_score", sa.Float(), nullable=False, server_default="0.35"),
        sa.Column("assumed_level", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("learning_velocity", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hint_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ask_simple_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_weak", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_interacted_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.CheckConstraint("mastery_score >= 0.0 AND mastery_score <= 1.0", name="ck_user_topic_mastery_score_range"),
        sa.CheckConstraint("assumed_level >= 0.0 AND assumed_level <= 1.0", name="ck_user_topic_mastery_assumed_level_range"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_user_topic_mastery_unique",
        "user_topic_mastery",
        ["user_id", "topic"],
        unique=True,
    )
    op.create_index(
        "idx_user_topic_mastery_weak",
        "user_topic_mastery",
        ["user_id", "is_weak", "mastery_score"],
        unique=False,
    )
    op.create_index(
        "idx_user_topic_mastery_recent",
        "user_topic_mastery",
        ["user_id", sa.text("updated_at DESC")],
        unique=False,
    )

    op.create_table(
        "user_learning_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("topic_mastery_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("subject", sa.String(length=50), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False, server_default="practice_interaction"),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("user_answer", sa.Text(), nullable=True),
        sa.Column("assistant_response", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hints_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.String(length=100), nullable=True),
        sa.Column("interaction_signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("detected_patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mastery_before", sa.Float(), nullable=False, server_default="0.35"),
        sa.Column("mastery_after", sa.Float(), nullable=False, server_default="0.35"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["topic_mastery_id"], ["user_topic_mastery.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_user_learning_events_user_time",
        "user_learning_events",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_user_learning_events_topic_time",
        "user_learning_events",
        ["user_id", "topic", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_user_learning_events_success",
        "user_learning_events",
        ["user_id", "success", sa.text("created_at DESC")],
        unique=False,
    )

    op.create_index(
        "idx_user_mistake_patterns_recent",
        "user_mistake_patterns",
        ["user_id", sa.text("last_seen_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_user_mistake_patterns_frequency",
        "user_mistake_patterns",
        ["user_id", sa.text("frequency DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_user_mistake_patterns_frequency", table_name="user_mistake_patterns")
    op.drop_index("idx_user_mistake_patterns_recent", table_name="user_mistake_patterns")

    op.drop_index("idx_user_learning_events_success", table_name="user_learning_events")
    op.drop_index("idx_user_learning_events_topic_time", table_name="user_learning_events")
    op.drop_index("idx_user_learning_events_user_time", table_name="user_learning_events")
    op.drop_table("user_learning_events")

    op.drop_index("idx_user_topic_mastery_recent", table_name="user_topic_mastery")
    op.drop_index("idx_user_topic_mastery_weak", table_name="user_topic_mastery")
    op.drop_index("idx_user_topic_mastery_unique", table_name="user_topic_mastery")
    op.drop_table("user_topic_mastery")
