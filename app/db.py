# db.py
import sqlite3
import time
from typing import Optional, Tuple, List

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id   INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            enabled    INTEGER NOT NULL DEFAULT 1,
            updated_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_posts (
            post_id TEXT PRIMARY KEY,
            first_seen_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gacha_notices (
            post_id     TEXT PRIMARY KEY,
            created_at  TEXT NOT NULL,
            text        TEXT NOT NULL,
            media_urls  TEXT NOT NULL DEFAULT '[]',
            post_url    TEXT NOT NULL,
            first_seen_at INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn

def upsert_guild_config(conn: sqlite3.Connection, guild_id: int, channel_id: int, enabled: int = 1) -> None:
    conn.execute("""
        INSERT INTO guild_config(guild_id, channel_id, enabled, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id=excluded.channel_id,
            enabled=excluded.enabled,
            updated_at=excluded.updated_at
    """, (guild_id, channel_id, enabled, int(time.time())))
    conn.commit()

def set_enabled(conn: sqlite3.Connection, guild_id: int, enabled: int) -> None:
    conn.execute("""
        UPDATE guild_config
        SET enabled=?, updated_at=?
        WHERE guild_id=?
    """, (enabled, int(time.time()), guild_id))
    conn.commit()

def get_guild_config(conn: sqlite3.Connection, guild_id: int) -> Optional[Tuple[int, int]]:
    cur = conn.execute("SELECT channel_id, enabled FROM guild_config WHERE guild_id=?", (guild_id,))
    row = cur.fetchone()
    return (int(row[0]), int(row[1])) if row else None

def list_enabled_channels(conn: sqlite3.Connection) -> List[Tuple[int, int]]:
    cur = conn.execute("SELECT guild_id, channel_id FROM guild_config WHERE enabled=1")
    return [(int(g), int(c)) for (g, c) in cur.fetchall()]

def seen(conn: sqlite3.Connection, post_id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM seen_posts WHERE post_id=?", (post_id,))
    return cur.fetchone() is not None

def mark_seen(conn: sqlite3.Connection, post_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO seen_posts(post_id, first_seen_at) VALUES(?, ?)", (post_id, int(time.time())))
    conn.commit()

def save_gacha_notice(conn: sqlite3.Connection, post_id: str, created_at: str, text: str, media_urls: list, post_url: str) -> None:
    import json
    conn.execute("""
        INSERT OR IGNORE INTO gacha_notices(post_id, created_at, text, media_urls, post_url, first_seen_at)
        VALUES(?, ?, ?, ?, ?, ?)
    """, (post_id, created_at, text, json.dumps(media_urls), post_url, int(time.time())))
    conn.commit()

def get_recent_gacha_notices(conn: sqlite3.Connection, limit: int = 10) -> list:
    import json
    cur = conn.execute("""
        SELECT post_id, created_at, text, media_urls, post_url
        FROM gacha_notices
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    return [
        {
            "post_id": r[0],
            "created_at": r[1],
            "text": r[2],
            "media_urls": json.loads(r[3]),
            "post_url": r[4],
        }
        for r in rows
    ]