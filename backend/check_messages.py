import asyncio
from db.connection import get_db

async def check():
    db = await get_db()
    messages = await db.fetch("SELECT * FROM messages WHERE content = 'test content'")
    print(f"Found {len(messages)} messages successfully saved by Celery!")

asyncio.run(check())
