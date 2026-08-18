import unittest

from job_matcher.daily_report import ReportJob, mark_cross_platform_duplicates, select_jobs, validate_greetings


def make_job(score: int, number: int) -> ReportJob:
    return ReportJob(
        score=score, tier="值得沟通", job_id=f"liepin:{number}", source="liepin", source_job_id=str(number), fingerprint=f"fp-{number}",
        name=f"岗位{number}", company=f"公司{number}", location="深圳", salary="20-30k",
        education="本科", work_years="3-5年", industry="人工智能", url="https://example.com",
        matched=["方案设计"], gaps=[], verdict="匹配", greeting_focus=["方案设计"], greeting=None,
        is_supplemental=False, status="pending", detail="完整岗位职责" * 20,
    )


class SelectionTests(unittest.TestCase):
    def _select(self, high_count: int):
        jobs = [make_job(85, i) for i in range(high_count)]
        jobs += [make_job(81 - i, 100 + i) for i in range(10)]
        return select_jobs(jobs, threshold=82, consider_threshold=75, minimum_high=15, fallback_count=5)

    def test_selection_boundaries(self):
        self.assertEqual(len(self._select(10)), 15)
        self.assertEqual(len(self._select(14)), 19)
        self.assertEqual(len(self._select(15)), 15)
        self.assertEqual(len(self._select(29)), 29)
        self.assertEqual(len(self._select(35)), 30)

    def test_only_fallback_jobs_are_marked_supplemental(self):
        selected = self._select(10)
        self.assertFalse(any(job.is_supplemental for job in selected[:10]))
        self.assertTrue(all(job.is_supplemental for job in selected[10:]))

    def test_cross_platform_duplicates_are_kept_and_marked(self):
        liepin = make_job(82, 1)
        zhilian = make_job(81, 2)
        zhilian.source, zhilian.source_job_id, zhilian.job_id = "zhilian", "2", "zhilian:2"
        zhilian.name, zhilian.company, zhilian.detail = liepin.name, liepin.company, liepin.detail
        jobs = mark_cross_platform_duplicates([liepin, zhilian])
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].duplicate_group, jobs[1].duplicate_group)
        self.assertEqual(jobs[0].duplicate_sources, ["liepin", "zhilian"])

    def test_headhunters_are_capped_and_never_appear_in_top_three(self):
        jobs = []
        for index in range(8):
            item = make_job(90 - index, index); item.recruiter_type = "unknown"; jobs.append(item)
        for index in range(4):
            item = make_job(95 - index, 100 + index); item.recruiter_type = "headhunter"; jobs.append(item)
        selected = [item for item in select_jobs(jobs, threshold=82, consider_threshold=75, minimum_high=15, fallback_count=5, max_headhunter_share=20, headhunter_free_top_n=3) if not item.is_excluded]
        self.assertTrue(all(item.recruiter_type != "headhunter" for item in selected[:3]))
        self.assertLessEqual(sum(item.recruiter_type == "headhunter" for item in selected) * 100, len(selected) * 20)


class GreetingValidationTests(unittest.TestCase):
    def test_rejects_missing_or_invalid_greeting(self):
        job = make_job(80, 1)
        with self.assertRaises(ValueError):
            validate_greetings([job], {})
        with self.assertRaises(ValueError):
            validate_greetings([job], {"1": "太短"})

    def test_accepts_valid_greeting_and_ignores_low_score(self):
        high, low = make_job(80, 1), make_job(65, 2)
        greeting = "AI解决方案顾问，可独立搭建AI Agent方案。熟悉Workflow、Skill、MCP及API接入，已完成示例业务工作流和示例Agent原型，覆盖需求分析、流程拆解、联调与交付。贵司强调方案设计，与我将业务诉求转为可实施能力的实践契合，期待进一步沟通。"
        self.assertGreaterEqual(len(greeting), 100)
        self.assertLessEqual(len(greeting), 130)
        validate_greetings([high, low], {"liepin:1": greeting})

    def test_rejects_missing_technology_or_output(self):
        job = make_job(80, 1)
        missing_technology = "AI解决方案顾问，可独立完成企业级AI Agent项目。擅长需求分析和业务流程拆解，已完成示例业务工作流和示例Agent原型，能够推动联调、项目交付及方案设计，并将模糊诉求转化为清晰可执行方案，与贵司岗位职责契合，希望进一步沟通交流。"
        missing_output = "AI解决方案顾问，可独立完成企业级AI Agent方案。熟悉Workflow、Skill、MCP和API接入，能够开展需求分析、流程拆解、联调与交付推进，并清晰划分模型及规则边界。贵司强调方案设计，与我的项目实践契合，希望进一步沟通交流。"
        with self.assertRaises(ValueError):
            validate_greetings([job], {"liepin:1": missing_technology})
        with self.assertRaises(ValueError):
            validate_greetings([job], {"liepin:1": missing_output})

    def test_rejects_inflated_python_claim(self):
        job = make_job(80, 1)
        greeting = "AI解决方案顾问，可独立搭建企业级AI Agent方案。精通Python并熟悉Workflow、Skill、MCP和API接入，已完成示例业务工作流和示例Agent原型，覆盖需求分析、流程拆解、联调和交付推进。贵司强调方案设计，与我的项目实践高度契合，希望进一步沟通交流。"
        with self.assertRaises(ValueError):
            validate_greetings([job], {"liepin:1": greeting})

    def test_rejects_length_compliant_but_truncated_greeting(self):
        job = make_job(80, 1)
        greeting = "AI解决方案顾问，独立推进企业AI Agent实践。贵司强调方案设计，我熟悉Codex、Claude Code、Workflow、Skill和API，已完成示例业务工作流及示例Agent原型并推动联调，覆盖需求拆解、产品规划和交付推进，也可将复杂流程沉。"
        self.assertGreaterEqual(len(greeting), 100)
        self.assertLessEqual(len(greeting), 130)
        with self.assertRaisesRegex(ValueError, "不能截断句子"):
            validate_greetings([job], {"liepin:1": greeting})
