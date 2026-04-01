"""add topic blocks and decision logs

Revision ID: 9f3a7d2b1c4e
Revises: d6e9e6219669
Create Date: 2026-04-01 14:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9f3a7d2b1c4e"
down_revision: Union[str, Sequence[str], None] = "d6e9e6219669"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "topic_blocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("subject", sa.String(length=50), nullable=True),
        sa.Column("topic_label", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("centroid_embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
        sa.Column("last_question_embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_topic_blocks_session",
        "topic_blocks",
        ["session_id", sa.text("updated_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_topic_blocks_embedding",
        "topic_blocks",
        ["centroid_embedding"],
        unique=False,
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"centroid_embedding": "vector_cosine_ops"},
    )

    op.add_column("messages", sa.Column("block_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_messages_block",
        "messages",
        "topic_blocks",
        ["block_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_messages_block", "messages", ["block_id", "created_at"], unique=False)

    op.create_table(
        "topic_routing_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("block_id", sa.String(length=36), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("decision_type", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("scores_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("thresholds_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("anchors_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model_versions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["block_id"], ["topic_blocks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_topic_routing_decisions_session",
        "topic_routing_decisions",
        ["session_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "user_mistake_patterns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("subject", sa.String(length=50), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("mistake_code", sa.String(length=100), nullable=True),
        sa.Column("mistake_label", sa.String(length=255), nullable=False),
        sa.Column("frequency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_user_mistake_patterns_unique",
        "user_mistake_patterns",
        ["user_id", "topic", "mistake_label"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_user_mistake_patterns_unique", table_name="user_mistake_patterns")
    op.drop_table("user_mistake_patterns")
    op.drop_index("idx_topic_routing_decisions_session", table_name="topic_routing_decisions")
    op.drop_table("topic_routing_decisions")
    op.drop_index("idx_messages_block", table_name="messages")
    op.drop_constraint("fk_messages_block", "messages", type_="foreignkey")
    op.drop_column("messages", "block_id")
    op.drop_index("idx_topic_blocks_embedding", table_name="topic_blocks")
    op.drop_index("idx_topic_blocks_session", table_name="topic_blocks")
    op.drop_table("topic_blocks")
