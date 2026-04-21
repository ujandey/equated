import asyncio
import asyncpg
import time

async def main():
    dsn = "postgresql://postgres.fqiiuadntiiaucugqjdd:Oyasumipunpun%402007@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
    c = await asyncpg.connect(dsn)
    uid = "00000000-0000-0000-0000-000000000000"

    # Test 1: users query
    t0 = time.perf_counter()
    try:
        row = await asyncio.wait_for(
            c.fetchrow("SELECT credits, tier FROM users WHERE id = $1", uid),
            timeout=5
        )
        print(f"[{(time.perf_counter()-t0)*1000:.0f}ms] users: {dict(row) if row else 'NOT FOUND'}")
    except Exception as e:
        print(f"[{(time.perf_counter()-t0)*1000:.0f}ms] users ERROR: {type(e).__name__}: {e}")

    # Test 2: solves query
    from datetime import date
    today = date.today()
    t0 = time.perf_counter()
    try:
        row = await asyncio.wait_for(
            c.fetchrow("SELECT COUNT(*) as cnt FROM solves WHERE user_id = $1 AND DATE(created_at) = $2", uid, today),
            timeout=5
        )
        print(f"[{(time.perf_counter()-t0)*1000:.0f}ms] solves: {dict(row) if row else 'NONE'}")
    except Exception as e:
        print(f"[{(time.perf_counter()-t0)*1000:.0f}ms] solves ERROR: {type(e).__name__}: {e}")

    # Test 3: sessions query (known to work)
    t0 = time.perf_counter()
    try:
        rows = await asyncio.wait_for(
            c.fetch("SELECT id, title FROM sessions WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 5", uid),
            timeout=5
        )
        print(f"[{(time.perf_counter()-t0)*1000:.0f}ms] sessions: {len(rows)} rows")
    except Exception as e:
        print(f"[{(time.perf_counter()-t0)*1000:.0f}ms] sessions ERROR: {type(e).__name__}: {e}")

    # Test 4: Pool behavior simulation
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5, command_timeout=10)
    print(f"\nPool: size={pool.get_size()}, free={pool.get_idle_size()}")
    
    # Concurrent queries
    t0 = time.perf_counter()
    try:
        results = await asyncio.wait_for(asyncio.gather(
            pool.fetchrow("SELECT credits, tier FROM users WHERE id = $1", uid),
            pool.fetchrow("SELECT COUNT(*) as cnt FROM solves WHERE user_id = $1 AND DATE(created_at) = $2", uid, today),
            pool.fetch("SELECT id FROM sessions WHERE user_id = $1 LIMIT 5", uid),
        ), timeout=10)
        print(f"[{(time.perf_counter()-t0)*1000:.0f}ms] Concurrent: all OK")
    except Exception as e:
        print(f"[{(time.perf_counter()-t0)*1000:.0f}ms] Concurrent ERROR: {type(e).__name__}: {e}")

    await pool.close()
    await c.close()

asyncio.run(main())
