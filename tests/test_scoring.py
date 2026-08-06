import unittest

from job_matcher.scoring import score_job


class ScoringTests(unittest.TestCase):
    def test_matching_skills_raise_score(self):
        result = score_job("五年 Python、SQL、Docker 开发经验", {"jobName": "Python开发", "description": "需要 Python、SQL、Docker"}, "Python开发")
        self.assertEqual(result.breakdown["岗位方向"], 30)
        self.assertEqual(result.breakdown["技术能力"], 20)
        self.assertGreaterEqual(result.score, 50)
        self.assertEqual(result.missing_skills, [])

    def test_unrecognised_dimension_never_gets_free_points(self):
        result = score_job("负责客户方案", {"jobName": "AI解决方案架构师", "description": "职责待定"}, "AI解决方案架构师")
        self.assertEqual(result.breakdown["核心职责"], 0)
        self.assertEqual(result.breakdown["技术能力"], 0)
        self.assertEqual(result.breakdown["业务领域"], 0)


    def test_missing_skill_is_reported(self):
        result = score_job("Python 开发经验", {"description": "Python、Kubernetes"})
        self.assertIn("kubernetes", result.missing_skills)
