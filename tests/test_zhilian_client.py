import json
import unittest
from unittest.mock import patch

from job_matcher.zhilian_client import ZhilianReadError, fetch_zhilian_detail, search_zhilian_jobs


def search_row():
    return {
        "cityId": "765", "cityDistrict": "南山", "companyName": "示例科技",
        "industryName": "人工智能", "education": "本科", "workingExp": "3-5年",
        "jobDetailData": {"position": {
            "base": {"positionNumber": "CC123J456", "positionName": "AI解决方案架构师",
                     "salary": "2-4万", "education": "本科", "positionWorkingExp": "3-5年"},
            "desc": {"description": "<div>完整岗位职责</div>" * 20},
        }},
    }


class ZhilianClientTests(unittest.TestCase):
    @patch("job_matcher.zhilian_client._fetch_text")
    def test_search_normalises_public_result(self, fetch):
        fetch.return_value = "<script>__INITIAL_STATE__=" + json.dumps({"positionList": [search_row()]}, ensure_ascii=False) + "</script>"
        jobs = search_zhilian_jobs("FDE")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["jobId"], "zhilian:CC123J456")
        self.assertEqual(jobs[0]["location"], "深圳·南山")
        self.assertGreaterEqual(len(jobs[0]["embeddedDetail"]), 80)

    @patch("job_matcher.zhilian_client._fetch_text")
    def test_detail_reads_complete_jd(self, fetch):
        position = {"jobDesc": "<div>完整岗位职责</div>" * 20}
        fetch.return_value = "__INITIAL_STATE__=" + json.dumps({"jobDetail": {"detailedPosition": position}}, ensure_ascii=False)
        detail = fetch_zhilian_detail({"sourceJobId": "CC123J456", "jobDetailUrl": "https://example.test"})
        self.assertGreaterEqual(len(detail.text), 80)

    @patch("job_matcher.zhilian_client._fetch_text")
    def test_stops_on_security_check(self, fetch):
        fetch.return_value = "__INITIAL_STATE__=" + json.dumps({"isVerification": True, "positionList": []})
        with self.assertRaises(ZhilianReadError) as context:
            search_zhilian_jobs("FDE")
        self.assertEqual(context.exception.code, "SECURITY_CHECK")


if __name__ == "__main__":
    unittest.main()
