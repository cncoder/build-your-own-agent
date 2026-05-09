"""
memory/store.py — SQLite-based short-term memory for lena-v0.8
Zero dependencies beyond Python stdlib.

Design: one row per message, one table per session index.
Only session history is stored here; long-term facts go to MemDir.
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path


class MemoryStore:
    """
    SQLite short-term memory. Zero dependencies beyond stdlib.
    Stores per-session message history, survives process restarts within session_id.

    Separate responsibility from MemDir:
      - store: sequential session history (what was said this session)
      - MemDir: cross-session facts (what is true about the user)
    """

    def __init__(self, db_path: str = "~/.lena/memory.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        # Fresh connection per call — simple, correct at this scale
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id      TEXT PRIMARY KEY,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL,   -- JSON-encoded (str or list)
                    created    TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_session "
                "ON messages(session_id, id)"
            )

    def create_session(self, session_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions VALUES (?, ?, ?)",
                (session_id, now, now)
            )

    def append_message(self, session_id: str, role: str, content) -> None:
        """Append a message. Content can be str or list (tool_use blocks)."""
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created) "
                "VALUES (?, ?, ?, ?)",
                (session_id, role, json.dumps(content, ensure_ascii=False), now)
            )
            conn.execute(
                "UPDATE sessions SET updated=? WHERE id=?", (now, session_id)
            )

    def load_messages(self, session_id: str) -> list[dict]:
        """Load all messages for a session, ordered by insertion."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id=? ORDER BY id",
                (session_id,)
            ).fetchall()
        return [{"role": r, "content": json.loads(c)} for r, c in rows]

    def list_sessions(self, limit: int = 10) -> list[dict]:
        """Return recent sessions, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, created, updated FROM sessions "
                "ORDER BY updated DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"id": r[0], "created": r[1], "updated": r[2]} for r in rows]
