-- ==============================================================
-- MIGRATION 001 — Initial Schema
-- Applies the complete Equated database schema
-- ==============================================================

-- This migration is identical to schema.sql for the initial setup.
-- Future migrations will be incremental (002_add_hints.sql, etc.)

\i ../schema.sql

-- Verify
SELECT 'Migration 001 complete — ' || COUNT(*) || ' tables created'
FROM information_schema.tables
WHERE table_schema = 'public';
