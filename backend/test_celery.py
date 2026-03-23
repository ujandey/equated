import asyncio
import uuid
from db.connection import get_db
from workers.tasks import save_chat_message

async def setup():
    db = await get_db()
    fake_user = str(uuid.uuid4())
    await db.execute("INSERT INTO users (id, email) VALUES ($1, $2)", fake_user, f"{fake_user}@test.com")
    fake_session = str(uuid.uuid4())
    await db.execute("INSERT INTO sessions (id, user_id, title) VALUES ($1, $2, $3)", fake_session, fake_user, "test session")
    return fake_session

session_id = asyncio.run(setup())
print(f"Created session {session_id}. Dispatching task...")
result = save_chat_message.delay(session_id, "user", "test content", {"test": True})
print(f"Task dispatched with ID {result.id}")
