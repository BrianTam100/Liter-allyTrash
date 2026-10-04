"""Accounts and collection records in TigerData PostgreSQL, or local SQLite."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


class Database:
    def __init__(self, url: str, local_path: str):
        self.url = url
        self.local_path = local_path
        self.is_tiger = bool(url)

    @contextmanager
    def connect(self):
        if self.is_tiger:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict
            from psycopg.rows import dict_row

            settings = conninfo_to_dict(self.url)
            # Preserve verify-full/verify-ca if supplied; always require TLS.
            if settings.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
                settings["sslmode"] = "require"
            conn = psycopg.connect(**settings, connect_timeout=5, row_factory=dict_row)
        else:
            Path(self.local_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.local_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, conn, query, params=()):
        return conn.execute(query.replace("?", "%s") if self.is_tiger else query, params)

    def initialize(self):
        with self.connect() as conn:
            identity = "BIGSERIAL PRIMARY KEY" if self.is_tiger else "INTEGER PRIMARY KEY AUTOINCREMENT"
            timestamp = "TIMESTAMPTZ" if self.is_tiger else "TEXT"
            conn.execute(f"""CREATE TABLE IF NOT EXISTS lt_users (
                id {identity}, email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
                created_at {timestamp} NOT NULL)""")
            conn.execute(f"""CREATE TABLE IF NOT EXISTS lt_collections (
                id {identity}, user_id BIGINT NOT NULL REFERENCES lt_users(id),
                category TEXT NOT NULL CHECK (category IN ('trash', 'recycling')),
                item_name TEXT NOT NULL,
                item_count INTEGER NOT NULL CHECK (item_count BETWEEN 1 AND 1000),
                request_id TEXT NOT NULL UNIQUE, created_at {timestamp} NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS lt_collections_user_time ON lt_collections(user_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS lt_collections_time ON lt_collections(created_at)")

    def user(self, user_id):
        with self.connect() as conn:
            row = self.execute(conn, "SELECT id, email, display_name FROM lt_users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def user_by_email(self, email):
        with self.connect() as conn:
            row = self.execute(conn, "SELECT * FROM lt_users WHERE email = ?", (email,)).fetchone()
            return dict(row) if row else None

    def create_user(self, email, name, password_hash):
        with self.connect() as conn:
            row = self.execute(conn, """INSERT INTO lt_users
                (email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?) RETURNING id""",
                (email, name, password_hash, self.now())).fetchone()
            return row["id"]

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def add_collection(self, user_id, category, count, request_id, item_name):
        with self.connect() as conn:
            cursor = self.execute(conn, """INSERT INTO lt_collections
                (user_id, category, item_count, request_id, item_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(request_id) DO NOTHING""",
                (user_id, category, count, request_id, item_name, self.now()))
            return cursor.rowcount == 1

    def leaderboard(self, period="all"):
        days = {"week": 7, "month": 30}.get(period)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days else "1970-01-01T00:00:00+00:00"
        with self.connect() as conn:
            rows = self.execute(conn, """WITH scores AS (
                SELECT u.id, u.display_name, COALESCE(SUM(c.item_count), 0) AS items,
                    COUNT(c.id) AS collections,
                    COALESCE(SUM(CASE WHEN c.category = 'recycling' THEN c.item_count ELSE 0 END), 0) AS recycled,
                    COALESCE(SUM(CASE WHEN c.category = 'recycling' THEN c.item_count * 10 ELSE 0 END), 0) AS points
                FROM lt_users u LEFT JOIN lt_collections c ON c.user_id = u.id AND c.created_at >= ?
                GROUP BY u.id, u.display_name
            ) SELECT *, RANK() OVER (ORDER BY recycled DESC) AS rank FROM scores
                WHERE recycled > 0 ORDER BY recycled DESC, display_name, id LIMIT 50""", (since,)).fetchall()
            return [dict(row) for row in rows]

    def stats(self, user_id=None):
        with self.connect() as conn:
            query = """SELECT COALESCE(SUM(item_count), 0) AS items, COUNT(*) AS collections,
                COALESCE(SUM(CASE WHEN category = 'recycling' THEN item_count ELSE 0 END), 0) AS recycled
                FROM lt_collections"""
            row = self.execute(conn, query + (" WHERE user_id = ?" if user_id else ""), (user_id,) if user_id else ()).fetchone()
            result = dict(row)
            result["points"] = result["recycled"] * 10
            result["pilots"] = conn.execute("SELECT COUNT(*) AS total FROM lt_users").fetchone()["total"]
            return result

    def recent(self, user_id):
        with self.connect() as conn:
            rows = self.execute(conn, """SELECT category, item_name, item_count, created_at FROM lt_collections
                WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 6""", (user_id,)).fetchall()
            return [dict(row) for row in rows]
