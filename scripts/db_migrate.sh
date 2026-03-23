#!/bin/bash
# Run database migrations

echo "🗄️  Running database migrations..."

DB_URL="${DATABASE_URL:-postgresql://postgres:password@localhost:5432/equated}"

# Apply schema
psql "$DB_URL" -f database/schema.sql

# Apply seed data
echo "🌱 Seeding pre-solved problem library..."
psql "$DB_URL" -f database/seed.sql

echo "✅ Database migration complete."
