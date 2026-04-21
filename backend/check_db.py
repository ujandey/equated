import asyncio
import asyncpg

async def main():
    dsn = "postgresql://postgres.fqiiuadntiiaucugqjdd:Oyasumipunpun%402007@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
    c = await asyncpg.connect(dsn)
    
    # List all tables
    rows = await c.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    tables = [r['tablename'] for r in rows]
    print("TABLES:", tables)
    
    # Check if critical tables exist
    critical = ['users', 'sessions', 'messages', 'solves', 'credit_transactions', 'topic_blocks']
    for t in critical:
        exists = t in tables
        print(f"  {t}: {'EXISTS' if exists else 'MISSING'}")
    
    # Check users table for dev user
    try:
        dev_user = await c.fetchrow("SELECT id, email, credits, tier FROM users WHERE id = '00000000-0000-0000-0000-000000000000'")
        print(f"\nDEV USER: {dict(dev_user) if dev_user else 'NOT FOUND'}")
    except Exception as e:
        print(f"\nDEV USER CHECK ERROR: {e}")

    # Check users table columns
    try:
        cols = await c.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users' ORDER BY ordinal_position")
        print(f"\nUSERS COLUMNS: {[(r['column_name'], r['data_type']) for r in cols]}")
    except Exception as e:
        print(f"\nUSERS COLUMNS ERROR: {e}")
    
    await c.close()

asyncio.run(main())
