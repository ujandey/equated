"""
SQLAlchemy Models for Alembic Migrations

These declarative models mirror the database schema in database/schema.sql.
While the app uses raw asyncpg queries for performance, these models
are essential for Alembic to generate accurate schema revisions.

SOURCE OF TRUTH: database/schema.sql
Keep this file in sync with that SQL file.
"""

from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, ForeignKey, Text, func, Index
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=True)
    avatar_url = Column(Text, nullable=True)
    tier = Column(String(20), default='free')
    credits = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = 'sessions'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = Column(String(255), default='New Chat')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_sessions_user', Session.user_id, Session.updated_at.desc())


class Message(Base):
    __tablename__ = 'messages'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    session_id = Column(UUID(as_uuid=False), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    block_id = Column(UUID(as_uuid=False), ForeignKey('topic_blocks.id', ondelete='SET NULL'), nullable=True)
    role = Column(String(20), nullable=False)          # 'user' | 'assistant' | 'system'
    content = Column(Text, nullable=False)
    metadata_json = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_messages_session', Message.session_id, Message.created_at)


class Solve(Base):
    __tablename__ = 'solves'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_id = Column(UUID(as_uuid=False), ForeignKey('sessions.id'), nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    subject = Column(String(50), nullable=True)
    complexity = Column(String(20), nullable=True)
    model_used = Column(String(50), nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    cached = Column(Boolean, default=False)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_solves_user', Solve.user_id, Solve.created_at.desc())
Index('idx_solves_subject', Solve.subject)


class TopicBlock(Base):
    __tablename__ = 'topic_blocks'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    session_id = Column(UUID(as_uuid=False), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(20), nullable=False, default='active')
    subject = Column(String(50), nullable=True)
    topic_label = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)
    centroid_embedding = Column(Vector(1536), nullable=True)
    last_question_embedding = Column(Vector(1536), nullable=True)
    question_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_topic_blocks_session', TopicBlock.session_id, TopicBlock.updated_at.desc())
Index(
    'idx_topic_blocks_embedding',
    TopicBlock.centroid_embedding,
    postgresql_using='ivfflat',
    postgresql_with={'lists': 100},
    postgresql_ops={'centroid_embedding': 'vector_cosine_ops'},
)


class TopicRoutingDecision(Base):
    __tablename__ = 'topic_routing_decisions'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    session_id = Column(UUID(as_uuid=False), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False)
    block_id = Column(UUID(as_uuid=False), ForeignKey('topic_blocks.id', ondelete='SET NULL'), nullable=True)
    query_text = Column(Text, nullable=False)
    decision_type = Column(String(50), nullable=False)
    reason = Column(String(255), nullable=False)
    scores_json = Column(JSONB, default={})
    thresholds_json = Column(JSONB, default={})
    anchors_json = Column(JSONB, default={})
    model_versions_json = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_topic_routing_decisions_session', TopicRoutingDecision.session_id, TopicRoutingDecision.created_at.desc())


class UserMistakePattern(Base):
    __tablename__ = 'user_mistake_patterns'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    subject = Column(String(50), nullable=True)
    topic = Column(String(255), nullable=False)
    mistake_code = Column(String(100), nullable=True)
    mistake_label = Column(String(255), nullable=False)
    frequency = Column(Integer, default=1)
    evidence_json = Column(JSONB, default=[])
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class CreditTransaction(Base):
    __tablename__ = 'credit_transactions'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    amount = Column(Integer, nullable=False)            # positive = purchase, negative = deduction
    type = Column(String(20), nullable=False)           # 'purchase' | 'deduction' | 'bonus'
    description = Column(String(255), nullable=True)
    payment_id = Column(String(255), nullable=True)     # Razorpay payment ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_credits_user', CreditTransaction.user_id, CreditTransaction.created_at.desc())


class ModelUsage(Base):
    __tablename__ = 'model_usage'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=False), ForeignKey('users.id'), nullable=True)
    model = Column(String(50), nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_model_usage_date', ModelUsage.created_at)


class CacheEntry(Base):
    __tablename__ = 'cache_entries'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    query = Column(Text, nullable=False)
    solution = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)     # DeepSeek embedding dimension
    metadata_json = Column("metadata", JSONB, default={})
    hit_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index(
    'idx_cache_embedding',
    CacheEntry.embedding,
    postgresql_using='ivfflat',
    postgresql_with={'lists': 100},
    postgresql_ops={'embedding': 'vector_cosine_ops'},
)


class EmbeddingVector(Base):
    __tablename__ = 'embedding_vectors'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    source_type = Column(String(50), nullable=False)    # 'question' | 'concept' | 'library'
    source_id = Column(UUID(as_uuid=False), nullable=True)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_embed_source', EmbeddingVector.source_type, EmbeddingVector.source_id)


class AnalyticsEvent(Base):
    __tablename__ = 'analytics_events'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    event_type = Column(String(100), nullable=False)
    data = Column(JSONB, default={})
    user_id = Column(UUID(as_uuid=False), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_analytics_type', AnalyticsEvent.event_type, AnalyticsEvent.created_at)


class AdsEvent(Base):
    __tablename__ = 'ads_events'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    ad_type = Column(String(50), nullable=False)        # 'banner' | 'solution_page'
    event = Column(String(20), nullable=False)          # 'impression' | 'click'
    user_id = Column(UUID(as_uuid=False), ForeignKey('users.id'), nullable=True)
    page = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Index('idx_ads_events_date', AdsEvent.created_at)


class Admin(Base):
    __tablename__ = 'admins'
    id = Column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=False), ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
