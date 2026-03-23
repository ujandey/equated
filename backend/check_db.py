import asyncio
from db.connection import get_db

async def check_tables():
    db = await get_db()
    result = await db.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
    tables = [row['table_name'] for row in result]
    print(f"Tables in public schema: {tables}")

asyncio.run(check_tables())
