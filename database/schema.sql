-- ==============================================================
-- EQUATED — PostgreSQL Schema
-- Full DDL for all tables
-- Uses pgvector extension for embedding-based question cache
-- ==============================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Users ────────────────────────────────────────────
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    name        VARCHAR(255),
    avatar_url  TEXT,
    tier        VARCHAR(20)  DEFAULT 'free',         -- 'free' | 'paid'
    credits     INTEGER      DEFAULT 0,
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- ── Sessions (Chat Sessions) ────────────────────────
CREATE TABLE sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(255) DEFAULT 'New Chat',
    is_active   BOOLEAN      DEFAULT TRUE,
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_sessions_user ON sessions(user_id, updated_at DESC);

-- ── Messages ─────────────────────────────────────────
CREATE TABLE messages (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        VARCHAR(20)  NOT NULL,               -- 'user' | 'assistant' | 'system'
    content     TEXT         NOT NULL,
    metadata    JSONB        DEFAULT '{}',
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON messages(session_id, created_at);

-- ── Solves (completed problem solves) ────────────────
CREATE TABLE solves (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES sessions(id),
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    subject         VARCHAR(50),
    complexity      VARCHAR(20),
    model_used      VARCHAR(50),
    input_tokens    INTEGER     DEFAULT 0,
    output_tokens   INTEGER     DEFAULT 0,
    cost_usd        FLOAT       DEFAULT 0.0,
    cached          BOOLEAN     DEFAULT FALSE,
    verified        BOOLEAN     DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_solves_user    ON solves(user_id, created_at DESC);
CREATE INDEX idx_solves_subject ON solves(subject);

-- ── Credits ──────────────────────────────────────────
CREATE TABLE credit_transactions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount      INTEGER      NOT NULL,               -- positive = purchase, negative = deduction
    type        VARCHAR(20)  NOT NULL,               -- 'purchase' | 'deduction' | 'bonus'
    description VARCHAR(255),
    payment_id  VARCHAR(255),                        -- Razorpay payment ID
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_credits_user ON credit_transactions(user_id, created_at DESC);

-- ── Model Usage (cost tracking) ──────────────────────
CREATE TABLE model_usage (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id),
    model           VARCHAR(50)  NOT NULL,
    input_tokens    INTEGER      DEFAULT 0,
    output_tokens   INTEGER      DEFAULT 0,
    cost_usd        FLOAT        DEFAULT 0.0,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_model_usage_date ON model_usage(created_at);

-- ── Cache Entries (pgvector) ─────────────────────────
CREATE TABLE cache_entries (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query       TEXT         NOT NULL,
    solution    TEXT         NOT NULL,
    embedding   vector(1536),                        -- DeepSeek embedding dimension
    metadata    JSONB        DEFAULT '{}',
    hit_count   INTEGER      DEFAULT 0,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- IVFFlat index for fast similarity search
CREATE INDEX idx_cache_embedding ON cache_entries
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ── Embedding Vectors (standalone) ───────────────────
CREATE TABLE embedding_vectors (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type VARCHAR(50)  NOT NULL,               -- 'question' | 'concept' | 'library'
    source_id   UUID,
    text        TEXT         NOT NULL,
    embedding   vector(1536),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_embed_source ON embedding_vectors(source_type, source_id);

-- ── Analytics Events ─────────────────────────────────
CREATE TABLE analytics_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type  VARCHAR(100) NOT NULL,
    data        JSONB        DEFAULT '{}',
    user_id     UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_analytics_type ON analytics_events(event_type, created_at);

-- ── Ads Events ───────────────────────────────────────
CREATE TABLE ads_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ad_type     VARCHAR(50)  NOT NULL,               -- 'banner' | 'solution_page'
    event       VARCHAR(20)  NOT NULL,               -- 'impression' | 'click'
    user_id     UUID REFERENCES users(id),
    page        VARCHAR(255),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX idx_ads_events_date ON ads_events(created_at);

-- ── Admins ───────────────────────────────────────────
CREATE TABLE admins (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);
