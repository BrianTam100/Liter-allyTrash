"""Shared dashboard storage regressions; no cloud credentials required."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from BRH_Test.database import Database


class TigerDatabaseTests(unittest.TestCase):
    def test_cloud_startup_initializes_tables_and_preserves_url_options(self):
        connection = MagicMock()
        with patch("psycopg.connect", return_value=connection) as connect:
            db = Database(
                "  postgresql://tester:secret@example.invalid/shared"
                "?sslmode=verify-full&connect_timeout=12  ", "unused.db")
        self.assertTrue(db.is_tiger)
        self.assertEqual(connect.call_args.kwargs["connect_timeout"], "12")
        self.assertEqual(connect.call_args.kwargs["sslmode"], "verify-full")
        queries = [call.args[0] for call in connection.execute.call_args_list]
        self.assertIn("pg_advisory_xact_lock", queries[0])
        for table in ("lt_users", "lt_collections", "lt_detections"):
            self.assertTrue(any(f"CREATE TABLE IF NOT EXISTS {table}" in query for query in queries))
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    def test_tls_and_timeout_defaults_and_transaction_failure(self):
        with patch.object(Database, "initialize"):
            db = Database("postgresql://tester@example.invalid/shared?sslmode=disable", "unused.db")
        connection = MagicMock()
        with patch("psycopg.connect", return_value=connection) as connect:
            with self.assertRaisesRegex(RuntimeError, "request failed"):
                with db.connect():
                    raise RuntimeError("request failed")
        self.assertEqual(connect.call_args.kwargs["sslmode"], "require")
        self.assertEqual(connect.call_args.kwargs["connect_timeout"], "5")
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


class SharedVisitorTests(unittest.TestCase):
    def test_concurrent_servers_reuse_pilot_and_share_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "shared.db")
            first, second = Database("", path), Database("   ", path)
            self.assertFalse(second.is_tiger)
            first.initialize()
            with ThreadPoolExecutor(max_workers=2) as pool:
                ids = list(pool.map(
                    lambda db: db.create_user("pilot@example.invalid", "Pilot", ""),
                    (first, second)))
            self.assertEqual(ids[0], ids[1])
            first.add_collection(ids[0], "recycling", 2, "visitor-one", "Can")
            second.add_collection(ids[1], "trash", 1, "visitor-two", "Wrapper")
            self.assertEqual(first.stats(ids[0])["items"], 3)
            self.assertEqual(second.stats(ids[1])["points"], 20)
            self.assertEqual(len(second.recent(ids[1])), 2)
            # Registered accounts still reject duplicate signup attempts.
            first.create_user("member@example.invalid", "Member", "hash")
            with self.assertRaises(sqlite3.IntegrityError):
                second.create_user("member@example.invalid", "Other", "other-hash")


if __name__ == "__main__":
    unittest.main()
