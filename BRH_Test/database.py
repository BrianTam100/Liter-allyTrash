"""Accounts and collection records in TigerData PostgreSQL, or local SQLite."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


class Database:
    def __init__(self, url: str, local_path: str):
        self.url = (url or "").strip()
        self.local_path = local_path
        self.is_tiger = bool(self.url)
        # Prepare shared storage before the dashboard accepts any visitors.
        if self.is_tiger:
            self.initialize()

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
            settings.setdefault("connect_timeout", "5")
            conn = psycopg.connect(**settings, row_factory=dict_row)
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
            if self.is_tiger:
                # Serialize schema setup across servers sharing the database.
                # The transaction releases this lock on commit or rollback.
                conn.execute("SELECT pg_advisory_xact_lock(1936683636, 1)")
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
            real = "DOUBLE PRECISION" if self.is_tiger else "REAL"
            # One row per final AI reading; scan_id matches lt_collections.request_id once confirmed.
            conn.execute(f"""CREATE TABLE IF NOT EXISTS lt_detections (
                id {identity}, scan_id TEXT NOT NULL UNIQUE, user_id BIGINT REFERENCES lt_users(id),
                label TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('recycling', 'trash', 'unrecognized')),
                drop_off SMALLINT NOT NULL DEFAULT 0, score {real} NOT NULL,
                source TEXT NOT NULL CHECK (source IN ('browser', 'server', 'photo')),
                created_at {timestamp} NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS lt_detections_time ON lt_detections(created_at)")

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
            # Passwordless visitors share the Pilot account. Two servers may
            # create it simultaneously; reuse its ID without changing its data.
            conflict = " ON CONFLICT(email) DO NOTHING" if not password_hash else ""
            row = self.execute(conn, """INSERT INTO lt_users
                (email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)""" + conflict + " RETURNING id",
                (email, name, password_hash, self.now())).fetchone()
            if row is None:
                row = self.execute(conn, "SELECT id FROM lt_users WHERE email = ?", (email,)).fetchone()
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

    @staticmethod
    def since(period):
        days = {"week": 7, "month": 30}.get(period)
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days else "1970-01-01T00:00:00+00:00"

    def add_detection(self, scan_id, user_id, label, category, drop_off, score, source):
        with self.connect() as conn:
            cursor = self.execute(conn, """INSERT INTO lt_detections
                (scan_id, user_id, label, category, drop_off, score, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(scan_id) DO NOTHING""",
                (scan_id, user_id, label, category, int(drop_off), float(score), source, self.now()))
            return cursor.rowcount == 1

    def detection_summary(self, period="all"):
        with self.connect() as conn:
            row = dict(self.execute(conn, """SELECT COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN d.category = 'recycling' AND d.drop_off = 0 THEN 1 ELSE 0 END), 0) AS recycling,
                COALESCE(SUM(CASE WHEN d.category = 'trash' AND d.drop_off = 0 THEN 1 ELSE 0 END), 0) AS trash,
                COALESCE(SUM(CASE WHEN d.drop_off = 1 THEN 1 ELSE 0 END), 0) AS drop_off,
                COALESCE(SUM(CASE WHEN d.category = 'unrecognized' THEN 1 ELSE 0 END), 0) AS unrecognized,
                AVG(CASE WHEN d.category <> 'unrecognized' THEN d.score END) AS avg_score,
                COUNT(c.id) AS confirmed
                FROM lt_detections d LEFT JOIN lt_collections c ON c.request_id = d.scan_id
                WHERE d.created_at >= ?""", (self.since(period),)).fetchone())
        avg_score = row.pop("avg_score")
        row = {key: int(value or 0) for key, value in row.items()}
        row["avg_score"] = None if avg_score is None else float(avg_score)
        recognized = row["total"] - row["unrecognized"]
        row["confirm_rate"] = row["confirmed"] / recognized if recognized else None
        row["bins"] = [(name, row[key]) for name, key in (("Recycling", "recycling"), ("Trash", "trash"),
            ("Drop-off", "drop_off"), ("Unrecognized", "unrecognized"))]
        return row

    def detection_items(self, period="all"):
        with self.connect() as conn:
            rows = self.execute(conn, """SELECT d.label, d.category, d.drop_off, COUNT(*) AS detections,
                AVG(d.score) AS avg_score, COUNT(c.id) AS confirmed
                FROM lt_detections d LEFT JOIN lt_collections c ON c.request_id = d.scan_id
                WHERE d.created_at >= ? GROUP BY d.label, d.category, d.drop_off
                ORDER BY detections DESC, d.label LIMIT 50""", (self.since(period),)).fetchall()
            return [{**dict(row), "avg_score": float(row["avg_score"])} for row in rows]

    def detections(self, period="all", limit=100):
        with self.connect() as conn:
            rows = self.execute(conn, """SELECT d.label, d.category, d.drop_off, d.score, d.source, d.created_at,
                CASE WHEN c.id IS NULL THEN 0 ELSE 1 END AS confirmed
                FROM lt_detections d LEFT JOIN lt_collections c ON c.request_id = d.scan_id
                WHERE d.created_at >= ? ORDER BY d.created_at DESC, d.id DESC LIMIT ?""",
                (self.since(period), limit)).fetchall()
            return [dict(row) for row in rows]

    def stats(self, user_id=None):
        with self.connect() as conn:
            query = """SELECT COALESCE(SUM(item_count), 0) AS items, COUNT(*) AS collections,
                COALESCE(SUM(CASE WHEN category = 'recycling' THEN item_count ELSE 0 END), 0) AS recycled
                FROM lt_collections"""
            row = self.execute(conn, query + (" WHERE user_id = ?" if user_id else ""), (user_id,) if user_id else ()).fetchone()
            result = dict(row)
            result["points"] = result["recycled"] * 10
            return result

    def recent(self, user_id):
        with self.connect() as conn:
            rows = self.execute(conn, """SELECT category, item_name, item_count, created_at FROM lt_collections
                WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 6""", (user_id,)).fetchall()
            return [dict(row) for row in rows]
