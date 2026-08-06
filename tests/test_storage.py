import tempfile
import unittest
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import job_matcher.storage as storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data_dir, self.old_db_path = storage.DATA_DIR, storage.DB_PATH
        storage.DATA_DIR = Path(self.temp.name)
        storage.DB_PATH = storage.DATA_DIR / "matcher.db"
        storage.initialize()

    def tearDown(self):
        storage.DATA_DIR, storage.DB_PATH = self.old_data_dir, self.old_db_path
        self.temp.cleanup()

    def test_status_persists_and_fingerprint_is_excluded(self):
        storage.set_job_status("liepin:job-1", "same-role", "applied", "liepin")
        self.assertEqual(storage.get_job_statuses(["liepin:job-1"])["liepin:job-1"], "applied")
        ids, fingerprints = storage.get_excluded_identities("liepin")
        self.assertIn("liepin:job-1", ids)
        self.assertIn("same-role", fingerprints)
        self.assertEqual(storage.get_excluded_identities("zhilian"), (set(), set()))
        storage.set_job_status("liepin:job-1", "same-role", "pending", "liepin")
        self.assertEqual(storage.get_excluded_identities("liepin"), (set(), set()))

    def test_daily_history_keeps_dates_and_current_status(self):
        payload = [{"job_id": "liepin:job-1", "source": "liepin", "fingerprint": "fp", "score": 80, "is_supplemental": False}]
        storage.save_daily_report("2026-07-28", "old.html", payload)
        storage.save_daily_report("2026-07-29", "new.html", payload)
        storage.set_job_status("liepin:job-1", "fp", "dismissed", "liepin")
        self.assertEqual([item["report_date"] for item in storage.list_report_dates()], ["2026-07-29", "2026-07-28"])
        _, jobs = storage.load_daily_report("2026-07-28")
        self.assertEqual(jobs[0]["status"], "dismissed")

    def test_validation_requires_three_consecutive_days(self):
        base = {"passed": True, "search_count": 4, "result_count": 10, "detail_success": 5, "detail_total": 5}
        self.assertEqual(storage.record_source_validation("zhilian", "2026-07-27", base), 1)
        self.assertEqual(storage.record_source_validation("zhilian", "2026-07-28", base), 2)
        self.assertEqual(storage.record_source_validation("zhilian", "2026-07-29", base), 3)
        self.assertTrue(storage.get_source_health("zhilian")["enabled"])

    def test_validation_treats_friday_and_monday_as_consecutive_workdays(self):
        passed = {"passed": True}
        self.assertEqual(storage.record_source_validation("zhilian", "2026-07-24", passed), 1)
        self.assertEqual(storage.record_source_validation("zhilian", "2026-07-27", passed), 2)
        self.assertEqual(storage.record_source_validation("zhilian", "2026-07-28", passed), 3)
        self.assertTrue(storage.get_source_health("zhilian")["enabled"])

    def test_failed_validation_resets_gate(self):
        passed = {"passed": True}
        failed = {"passed": False, "error": "AUTH_REQUIRED"}
        storage.record_source_validation("zhilian", "2026-07-28", passed)
        self.assertEqual(storage.record_source_validation("zhilian", "2026-07-29", failed), 0)
        self.assertFalse(storage.get_source_health("zhilian")["enabled"])

    def test_application_statistics_count_current_status_by_applied_date(self):
        storage.set_job_status("liepin:job-1", "fp-1", "applied", "liepin")
        storage.set_job_status("zhilian:job-1", "fp-1", "applied", "zhilian")
        storage.set_job_status("liepin:job-old", "fp-old", "applied", "liepin")
        with closing(sqlite3.connect(storage.DB_PATH)) as connection, connection:
            connection.execute("UPDATE job_statuses SET applied_at='2026-07-29T09:00:00' WHERE job_id='liepin:job-1'")
            connection.execute("UPDATE job_statuses SET applied_at='2026-07-28T09:00:00' WHERE job_id='zhilian:job-1'")
            connection.execute("UPDATE job_statuses SET applied_at='2026-07-01T09:00:00' WHERE job_id='liepin:job-old'")
        stats = storage.get_application_statistics(as_of=date(2026, 7, 29))
        self.assertEqual(stats["today"], 1)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(len(stats["daily"]), 14)
        self.assertEqual(stats["daily"][-1], {"date": "2026-07-29", "label": "07-29", "count": 1})
        self.assertEqual(stats["daily"][-2]["count"], 1)
        self.assertEqual(stats["daily"][0]["count"], 0)

    def test_repeated_apply_does_not_move_date_and_undo_removes_count(self):
        storage.set_job_status("liepin:job-1", "fp", "applied", "liepin")
        with closing(sqlite3.connect(storage.DB_PATH)) as connection, connection:
            connection.execute("UPDATE job_statuses SET applied_at='2026-07-20T09:00:00' WHERE job_id='liepin:job-1'")
        storage.set_job_status("liepin:job-1", "fp", "applied", "liepin")
        with closing(sqlite3.connect(storage.DB_PATH)) as connection, connection:
            applied_at = connection.execute("SELECT applied_at FROM job_statuses WHERE job_id='liepin:job-1'").fetchone()[0]
        self.assertEqual(applied_at, "2026-07-20T09:00:00")
        storage.set_job_status("liepin:job-1", "fp", "pending", "liepin")
        self.assertEqual(storage.get_application_statistics()["total"], 0)
        storage.set_job_status("liepin:job-1", "fp", "applied", "liepin")
        with closing(sqlite3.connect(storage.DB_PATH)) as connection, connection:
            reapplied_at = connection.execute("SELECT applied_at FROM job_statuses WHERE job_id='liepin:job-1'").fetchone()[0]
        self.assertNotEqual(reapplied_at, "2026-07-20T09:00:00")
        self.assertEqual(storage.get_application_statistics()["total"], 1)

    def test_existing_applied_rows_receive_applied_date_during_migration(self):
        storage.DB_PATH.unlink()
        storage.DATA_DIR.mkdir(exist_ok=True)
        with closing(sqlite3.connect(storage.DB_PATH)) as connection, connection:
            connection.execute(
                """CREATE TABLE job_statuses (
                    job_id TEXT PRIMARY KEY, source TEXT NOT NULL DEFAULT 'liepin', fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL, updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "INSERT INTO job_statuses VALUES('liepin:legacy','liepin','fp','applied','2026-07-18T10:30:00')"
            )
        storage.initialize()
        with closing(sqlite3.connect(storage.DB_PATH)) as connection, connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(job_statuses)")}
            applied_at = connection.execute("SELECT applied_at FROM job_statuses WHERE job_id='liepin:legacy'").fetchone()[0]
        self.assertIn("applied_at", columns)
        self.assertEqual(applied_at, "2026-07-18T10:30:00")
