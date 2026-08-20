"""
backend/storage.py — ZYRA Local Storage Module

Provides SQLite-backed persistence for:
  - Memory (key-value pairs) — replaces memory/data.json
  - Conversations — chat history
  - User settings — preferences

Uses SQLite (ships with Python stdlib) so no external database
installation is required.
"""

import sqlite3
import os
import json

# Determine database path: use env var if set (packaged app),
# otherwise default to user's home directory
DB_DIR = os.environ.get(
    'ZYRA_DATA_DIR',
    os.path.join(os.path.expanduser('~'), '.zyra')
)
DB_PATH = os.path.join(DB_DIR, 'zyra.db')


def init_db():
    """Initialize the database schema if it doesn't exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memory (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            role      TEXT NOT NULL,
            content   TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def remember(key: str, value: str) -> None:
    """Store a key-value pair in memory."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO memory (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()


def recall(key: str) -> str | None:
    """Retrieve a value from memory by key. Returns None if not found."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT value FROM memory WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def save_conversation(role: str, content: str) -> int:
    """Save a conversation message. Returns the row ID."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "INSERT INTO conversations (role, content) VALUES (?, ?)",
        (role, content)
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def load_conversations(limit: int = 100) -> list[dict]:
    """Load recent conversation history."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT role, content FROM conversations ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_conversations() -> int:
    """Delete all conversation history. Returns count of deleted rows."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT COUNT(*) FROM conversations")
    count = cursor.fetchone()[0]
    conn.execute("DELETE FROM conversations")
    conn.commit()
    conn.close()
    return count


def get_setting(key: str, default: str | None = None) -> str | None:
    """Retrieve a user setting."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    """Store a user setting."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()


def get_db_path() -> str:
    """Return the database file path (for diagnostics)."""
    return DB_PATH


if __name__ == "__main__":
    # Quick test
    init_db()
    remember("test_key", "test_value")
    result = recall("test_key")
    print(f"SQLite storage working: {result}")
    save_conversation("user", "Hello, ZYRA!")
    save_conversation("assistant", "Hi there!")
    convos = load_conversations()
    print(f"Conversations: {convos}")
    print(f"DB path: {get_db_path()}")
