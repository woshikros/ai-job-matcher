import json
import tempfile
import unittest
from pathlib import Path

from job_matcher.profile_config import DEFAULT_PROFILE, load_candidate_profile


class ProfileConfigTests(unittest.TestCase):
    def test_defaults_do_not_contain_private_resume_facts(self):
        self.assertEqual(DEFAULT_PROFILE["output_facts"], ["示例业务工作流", "示例Agent原型", "示例Skill"])
        self.assertTrue(all("示例" in item for item in DEFAULT_PROFILE["output_facts"]))

    def test_loads_local_profile_without_writing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.local.json"
            data = {key: list(value) for key, value in DEFAULT_PROFILE.items()}
            data["output_facts"] = ["虚构测试成果"]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(load_candidate_profile(path)["output_facts"], ["虚构测试成果"])
