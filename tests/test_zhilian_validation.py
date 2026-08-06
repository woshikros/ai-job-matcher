import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_matcher.zhilian_client import ZhilianDetail
from job_matcher.zhilian_validation import run_validation


def jobs_for(query):
    return [
        {
            "jobId": f"zhilian:{query}-{number}", "sourceJobId": f"{query}-{number}",
            "jobName": f"{query}岗位{number}", "company": f"公司{number}",
            "location": "深圳·南山", "salary": "2-4万", "education": "本科",
            "workYears": "3-5年", "industry": "人工智能",
            "jobDetailUrl": f"https://example.test/{query}-{number}",
        }
        for number in range(5)
    ]


class ZhilianValidationTests(unittest.TestCase):
    @patch("job_matcher.zhilian_validation.record_source_validation", return_value=1)
    @patch("job_matcher.zhilian_validation.fetch_zhilian_detail")
    @patch("job_matcher.zhilian_validation.search_zhilian_jobs")
    def test_passes_with_stable_search_and_complete_details(self, search, detail, record):
        search.side_effect = lambda query, city, page: jobs_for(query)
        detail.return_value = ZhilianDetail("完整岗位职责" * 20, "https://example.test", {})
        with tempfile.TemporaryDirectory() as folder:
            result = run_validation("2026-07-29", Path(folder))
            self.assertTrue(result["passed"])
            self.assertEqual(result["detail_success"], 5)
            self.assertTrue(result["stable_ids"])
            self.assertTrue((Path(folder) / "zhilian-validation-2026-07-29.html").exists())
        record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
