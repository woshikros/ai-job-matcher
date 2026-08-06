import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import job_matcher.storage as storage
from job_matcher.backup import export_backup
from job_matcher.candidate_profile import extract_profile_suggestions, get_candidate_profile, profile_is_complete, profile_queries, save_candidate_profile
from job_matcher.daily_report import collect_liepin_candidates


class CandidateProfileTests(unittest.TestCase):
    def test_resume_suggestions_extract_skills_and_results(self):
        skills, results = extract_profile_suggestions("熟悉Workflow、MCP和API。负责搭建示例Agent并完成项目交付。")
        self.assertIn("MCP", skills)
        self.assertTrue(any("搭建" in item for item in results))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data, self.old_db = storage.DATA_DIR, storage.DB_PATH
        storage.DATA_DIR = Path(self.temp.name); storage.DB_PATH = storage.DATA_DIR / "matcher.db"; storage.initialize()

    def tearDown(self):
        storage.DATA_DIR, storage.DB_PATH = self.old_data, self.old_db
        self.temp.cleanup()

    def test_first_run_requires_profile(self):
        self.assertFalse(profile_is_complete(get_candidate_profile()))

    def test_profile_is_local_complete_and_drives_queries(self):
        storage.save_setting("resume_text", "示例简历")
        saved = save_candidate_profile({"cities": ["深圳", "广州"], "target_roles": ["AI解决方案架构师"], "salary_upper_floor": 25000, "excluded_keywords": [], "confirmed_skills": ["示例能力"], "confirmed_achievements": ["示例成果"]})
        self.assertTrue(profile_is_complete(saved)); self.assertIn("AI解决方案架构师", profile_queries(saved)); self.assertEqual(get_candidate_profile()["cities"], ["深圳", "广州"])
        keys = [item["key"] for item in export_backup().get("settings", [])]
        self.assertNotIn("candidate_profile", keys)

    @patch("job_matcher.daily_report.search_jobs")
    def test_collection_uses_each_city_and_profile_query(self, mocked):
        mocked.return_value = []
        collect_liepin_candidates(["深圳", "广州"], ["FDE", "AI产品经理"], 1, 20000)
        self.assertEqual(mocked.call_count, 4)
