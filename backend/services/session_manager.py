"""
Services — Session Manager

Stores and retrieves chat sessions and messages.
Maintains conversation context for follow-up questions.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class Message:
    """Single message in a chat session."""
    id: str = field(default_factory=lambda: str(uuid4()))
    role: str = "user"           # "user" | "assistant" | "system"
    content: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)  # model used, tokens, cost, etc.


@dataclass
class Session:
    """Chat session containing a sequence of messages."""
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    title: str = "New Chat"
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True


class SessionManager:
    """
    Manages chat sessions and messages.

    Responsibilities:
      - Create / retrieve / list / delete / rename sessions
      - Add messages to a session
      - Build context window for follow-up questions
      - Persist to database (Supabase Postgres)
    """

    async def create_session(self, user_id: str, title: str = "New Chat") -> Session:
        """Create a new chat session."""
        session = Session(user_id=user_id, title=title)
        await self._persist_session(session)
        return session

    async def get_session(self, session_id: str) -> Session | None:
        """Retrieve a session by ID."""
        from db.connection import get_db

        db = await get_db()
        row = await db.fetchrow(
            "SELECT * FROM sessions WHERE id = $1", session_id
        )
        if not row:
            return None
        return self._row_to_session(row)

    async def list_sessions(self, user_id: str, limit: int = 20) -> list[Session]:
        """List recent sessions for a user."""
        from db.connection import get_db

        db = await get_db()
        rows = await db.fetch(
            "SELECT * FROM sessions WHERE user_id = $1 ORDER BY updated_at DESC LIMIT $2",
            user_id, limit,
        )
        return [self._row_to_session(row) for row in rows]

    async def delete_session(self, session_id: str):
        """Delete a session and all its messages."""
        from db.connection import get_db

        db = await get_db()
        # Delete messages first (foreign key)
        await db.execute("DELETE FROM messages WHERE session_id = $1", session_id)
        await db.execute("DELETE FROM sessions WHERE id = $1", session_id)

    async def update_session_title(self, session_id: str, new_title: str):
        """Rename a session."""
        from db.connection import get_db

        db = await get_db()
        await db.execute(
            "UPDATE sessions SET title = $1, updated_at = $2 WHERE id = $3",
            new_title, datetime.utcnow(), session_id,
        )

    async def add_message(self, session_id: str, role: str, content: str, metadata: dict = None) -> Message:
        """Add a message to an existing session."""
        msg = Message(role=role, content=content, metadata=metadata or {})

        from db.connection import get_db
        db = await get_db()
        await db.execute(
            """INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            msg.id, session_id, msg.role, msg.content,
            json.dumps(msg.metadata), msg.created_at,
        )
        # Update session timestamp
        await db.execute(
            "UPDATE sessions SET updated_at = $1 WHERE id = $2",
            datetime.utcnow(), session_id,
        )
        return msg

    async def get_context_messages(self, session_id: str, max_messages: int = 10) -> list[dict]:
        """
        Build context window for AI model calls.
        Returns last N messages in OpenAI-compatible format.
        """
        from db.connection import get_db

        db = await get_db()
        rows = await db.fetch(
            """SELECT role, content FROM messages
               WHERE session_id = $1
               ORDER BY created_at DESC LIMIT $2""",
            session_id, max_messages,
        )
        # Reverse to chronological order
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def get_message_count(self, session_id: str) -> int:
        """Get the total number of messages in a session."""
        from db.connection import get_db

        db = await get_db()
        count = await db.fetchval(
            "SELECT COUNT(*) FROM messages WHERE session_id = $1", session_id
        )
        return count or 0

    async def _persist_session(self, session: Session):
        """Save session to database."""
        from db.connection import get_db
        db = await get_db()
        await db.execute(
            """INSERT INTO sessions (id, user_id, title, created_at, updated_at, is_active)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            session.id, session.user_id, session.title,
            session.created_at, session.updated_at, session.is_active,
        )

    def _row_to_session(self, row) -> Session:
        """Convert a database row to a Session object."""
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_active=row.get("is_active", True),
        )


# Singleton
session_manager = SessionManager()
