import unittest
from datetime import date

from job_matcher.job_detail import _JobIntroParser, extract_platform_update_date


class JobDetailParserTests(unittest.TestCase):
    def test_extracts_job_intro_only(self):
        parser = _JobIntroParser()
        parser.feed('<dd data-selector="job-intro-content">职位描述<br>负责Agent交付<br>职位要求<br>理解MCP</dd><div>公司简介</div>')
        text = "".join(parser.parts)
        self.assertIn("负责Agent交付", text)
        self.assertIn("理解MCP", text)
        self.assertNotIn("公司简介", text)

    def test_extracts_platform_update_date(self):
        self.assertEqual(extract_platform_update_date('<span class="update-time">6月2日更新</span>', date(2026, 8, 18)), "2026-06-02")
        self.assertEqual(extract_platform_update_date('<span class="update-time">12月30日更新</span>', date(2026, 1, 5)), "2025-12-30")
        self.assertEqual(extract_platform_update_date('<span class="update-time">昨天更新</span>', date(2026, 8, 18)), "2026-08-17")
