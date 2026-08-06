import tempfile
import unittest
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import job_matcher.storage as storage
from job_matcher.backup import export_backup, restore_backup
from job_matcher.providers import normalise_provider_job, validate_provider_job
from job_matcher.scoring import score_job

class UnifiedScoringTests(unittest.TestCase):
    def test_ai_explanation_never_changes_score(self):
        job = {"jobName": "AI解决方案", "description": "负责客户需求分析、Agent方案和MCP集成"}
        resume = "负责需求分析、Agent方案、MCP集成和客户交付" * 10
        with patch("job_matcher.scoring._ai_note", return_value=None): without_ai = score_job(resume, job)
        with patch("job_matcher.scoring._ai_note", return_value="补充解释"): with_ai = score_job(resume, job)
        self.assertEqual(without_ai.score, with_ai.score); self.assertEqual(with_ai.ai_note, "补充解释")

    def test_unmet_hard_requirement_caps_score(self):
        result = score_job("擅长业务方案和客户交付" * 20, {"jobName": "开发工程师", "description": "精通Python，主导核心代码"})
        self.assertLessEqual(result.score, 69); self.assertTrue(result.hard_knockouts)

class ProviderContractTests(unittest.TestCase):
    def test_normalises_platform_fields(self):
        job = normalise_provider_job({"jobId": "123", "title": "FDE", "brandName": "示例公司", "url": "https://example.com/123"}, "demo")
        self.assertEqual(job["jobId"], "demo:123"); self.assertEqual(validate_provider_job(job), [])

class FreshnessAndBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.old_data_dir, self.old_db_path = storage.DATA_DIR, storage.DB_PATH
        storage.DATA_DIR = Path(self.temp.name); storage.DB_PATH = storage.DATA_DIR / "matcher.db"; storage.initialize()
    def tearDown(self):
        storage.DATA_DIR, storage.DB_PATH = self.old_data_dir, self.old_db_path; self.temp.cleanup()
    def _job(self): return {"job_id": "liepin:1", "source": "liepin", "fingerprint": "fp", "score": 80, "is_supplemental": False}
    def test_sighting_counts_unique_days(self):
        storage.save_daily_report("2026-08-03", "a.html", [self._job()]); storage.save_daily_report("2026-08-03", "a.html", [self._job()])
        _, first = storage.load_daily_report("2026-08-03"); self.assertTrue(first[0]["is_new"]); self.assertEqual(first[0]["seen_count"], 1)
        storage.save_daily_report("2026-08-04", "b.html", [self._job()]); _, second = storage.load_daily_report("2026-08-04")
        self.assertFalse(second[0]["is_new"]); self.assertEqual(second[0]["seen_count"], 2)
    def test_legacy_reports_are_backfilled_into_sightings(self):
        item = self._job()
        with closing(sqlite3.connect(storage.DB_PATH)) as connection, connection:
            connection.execute("DELETE FROM job_sightings")
            for report_date in ("2026-08-01", "2026-08-04"):
                connection.execute(
                    "INSERT INTO daily_reports(report_date,generated_at,html_path,summary) VALUES(?,?,?,?)",
                    (report_date, f"{report_date}T09:00:00", f"{report_date}.html", "{}"),
                )
                connection.execute(
                    "INSERT INTO daily_report_jobs(report_date,job_id,source,fingerprint,rank,score,is_supplemental,payload) VALUES(?,?,?,?,?,?,?,?)",
                    (report_date, item["job_id"], item["source"], item["fingerprint"], 1, 80, 0, json.dumps(item)),
                )
        storage.initialize(); sighting = storage.get_job_sightings([item["job_id"]])[item["job_id"]]
        self.assertEqual(sighting["first_seen"], "2026-08-01"); self.assertEqual(sighting["last_seen"], "2026-08-04"); self.assertEqual(sighting["seen_count"], 2)
    def test_backup_excludes_resume_and_restores_status(self):
        storage.save_setting("resume_text", "private resume"); storage.save_setting("theme", "light"); storage.set_job_status("liepin:1", "fp", "applied", "liepin")
        payload = export_backup(); self.assertNotIn("resume_text", {row["key"] for row in payload["tables"]["settings"]})
        storage.DB_PATH.unlink(); storage.initialize(); restore_backup(payload)
        self.assertEqual(storage.get_job_statuses(["liepin:1"])["liepin:1"], "applied"); self.assertEqual(storage.get_setting("theme"), "light")
