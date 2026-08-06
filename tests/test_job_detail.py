import unittest

from job_matcher.job_detail import _JobIntroParser


class JobDetailParserTests(unittest.TestCase):
    def test_extracts_job_intro_only(self):
        parser = _JobIntroParser()
        parser.feed('<dd data-selector="job-intro-content">职位描述<br>负责Agent交付<br>职位要求<br>理解MCP</dd><div>公司简介</div>')
        text = "".join(parser.parts)
        self.assertIn("负责Agent交付", text)
        self.assertIn("理解MCP", text)
        self.assertNotIn("公司简介", text)
