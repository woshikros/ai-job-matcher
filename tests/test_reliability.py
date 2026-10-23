"""All candidate and job text in this module is fictional."""
import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from test_daily_report import make_job
from job_matcher import daily_report as report, storage
from job_matcher.daily_cache import CachedReads, CachedReadBlocked
from job_matcher.job_detail import extract_platform_update_date
from job_matcher.job_safety import evaluate_eligibility, detail_content_issue, role_content
from job_matcher.rescore import rescore_saved_report
from job_matcher.scoring import score_job


SAMPLE='虚构候选人：本科，企业软件实施、需求分析、API、Workflow，使用Python制作示例原型。'
PROFILE={'cities':['深圳'],'target_roles':['AI解决方案架构师'],'priority_threshold':82,'consider_threshold':75,'cautious_fallback_count':5}


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.paths=patch.multiple(storage,DATA_DIR=self.root/'data',DB_PATH=self.root/'data/matcher.db')
        self.paths.start();storage.initialize()
    def tearDown(self):
        self.paths.stop();self.temp.cleanup()

    def test_failed_or_unknown_read_is_not_automatically_revisited(self):
        path=self.root/'cache.json';fetch=Mock(side_effect=TimeoutError('fictional timeout'))
        with self.assertRaises(TimeoutError):CachedReads(path).call(['sample-query'],fetch)
        with self.assertRaises(CachedReadBlocked):CachedReads(path).call(['sample-query'],fetch)
        self.assertEqual(fetch.call_count,1)

    def test_recovery_reuses_success_and_only_retries_failure(self):
        path=self.root/'cache.json';CachedReads(path).call(['ok'],lambda:[1])
        with self.assertRaises(RuntimeError):CachedReads(path).call(['failed'],Mock(side_effect=RuntimeError('sample failure')))
        recovery=CachedReads(path,retry_failed=True)
        self.assertEqual(recovery.call(['ok'],Mock(side_effect=AssertionError('revisited success'))),[1])
        self.assertEqual(recovery.call(['failed'],lambda:[2]),[2])

    def test_interrupted_read_keeps_no_retry_checkpoint(self):
        path=self.root/'cache.json'
        with self.assertRaises(KeyboardInterrupt):CachedReads(path).call(['q'],Mock(side_effect=KeyboardInterrupt))
        with self.assertRaises(CachedReadBlocked):CachedReads(path).call(['q'],Mock())

    def test_different_stable_ids_survive_same_company_title_and_text(self):
        first,second=make_job(85,1),make_job(80,2)
        second.company=first.company;second.name=first.name;second.fingerprint=first.fingerprint
        self.assertEqual(len(report._deduplicate_results([first,second])),2)
        second.source_job_id=first.source_job_id
        self.assertEqual(len(report._deduplicate_results([first,second])),1)

    def test_full_jd_change_invalidates_fingerprint(self):
        prefix='岗位职责：负责示例需求和方案。'*100
        self.assertNotEqual(report._fingerprint('虚构公司',prefix+'Java优先'),report._fingerprint('虚构公司',prefix+'Java必须'))

    def test_core_duties_after_company_intro_are_retained(self):
        text=role_content('公司介绍\n虚构背景。\n核心职责\n负责客户需求分析。\n任职要求\n表达清晰。')
        self.assertIn('负责客户需求分析',text);self.assertNotIn('虚构背景',text)

    def test_optional_industry_and_languages_are_not_hard_requirements(self):
        text='岗位职责：负责AI解决方案。\n任职要求：有实施经验。\n加分项：5年以上保险行业经验，精通Java。'
        self.assertNotEqual(evaluate_eligibility(SAMPLE,{},text,'active').verdict,'fail')

    def test_numbered_optional_item_does_not_hide_next_mandatory_item(self):
        text='岗位职责：负责AI方案。\n任职要求\n2、加分项：有Python经验。\n3、精通Java。'
        result=evaluate_eligibility(SAMPLE,{},text,'active')
        self.assertEqual(result.verdict,'fail');self.assertIn('java','；'.join(result.reasons))

    def test_alternative_languages_do_not_require_every_language(self):
        result=evaluate_eligibility(SAMPLE,{},'岗位职责：负责AI方案。\n任职要求：熟悉Python/Java至少一种语言。','active')
        self.assertNotIn('熟练掌握java','；'.join(result.reasons))

    def test_shenzhen_district_is_not_treated_as_another_city(self):
        text='岗位职责：负责方案。\n任职要求：必须到岗，工作地点宝安区。'
        result=evaluate_eligibility(SAMPLE,{'location':'宝安区'},text,'active')
        self.assertNotIn('不在目标城市','；'.join(result.reasons))
        other=evaluate_eligibility(SAMPLE,{'location':'广州市'},text,'active')
        self.assertIn('不在目标城市','；'.join(other.reasons))

    def test_search_metadata_cannot_inflate_role_score(self):
        job={'jobName':'文员','description':'负责普通文档归档。','query':'AI解决方案架构师','raw':{'advert':'Agent API Workflow'}}
        with patch('job_matcher.scoring._ai_note',return_value=None):
            scored=score_job(SAMPLE,job,['AI解决方案架构师'])
        self.assertEqual(scored.breakdown['岗位方向'],0)
        self.assertEqual(scored.breakdown['技术能力'],0)

    def test_optional_programming_does_not_reduce_core_technical_score(self):
        job={'jobName':'AI解决方案架构师','description':'岗位职责：需求分析、方案设计与API配置。'}
        with patch('job_matcher.scoring._ai_note',return_value=None):
            base=score_job(SAMPLE,job,['AI解决方案架构师'])
            extra=score_job(SAMPLE,{**job,'description':job['description']+'\n加分项：精通Java、Golang。'},['AI解决方案架构师'])
        self.assertEqual(base.breakdown['技术能力'],extra.breakdown['技术能力'])

    def test_prepared_pool_retains_backups_and_same_jd_greeting(self):
        jobs=[make_job(81,i) for i in range(8)]
        for j in jobs:j.score_version='v3';j.priority_threshold=82
        path=self.root/'2040-04-01.candidates.json'
        with patch.object(report,'get_candidate_profile',return_value=PROFILE):
            report.write_prepared_report(jobs,path)
            pool=report.load_prepared_jobs(path)
            self.assertEqual(len(pool),8)
            for item in pool[:3]:item.eligibility_verdict='fail'
            self.assertEqual(sum(not j.is_excluded for j in report.select_jobs(pool)),5)

    def test_manual_review_survives_unchanged_jd_but_not_changed_text(self):
        old=make_job(90,1);old.manual_review={'decision':'exclude','reason':'虚构人工复核理由'}
        fresh=make_job(90,1);report.apply_saved_review(fresh,old)
        self.assertTrue(fresh.is_excluded)
        changed=make_job(90,1);changed.fingerprint='new-fingerprint';changed.detail+='新增任职条件'
        report.apply_saved_review(changed,old)
        self.assertFalse(changed.is_excluded);self.assertIsNone(changed.manual_review)

    def test_relative_update_date_and_configurable_cutoff(self):
        reference=date(2040,4,1)
        self.assertEqual(extract_platform_update_date('30天前更新',reference),(reference-timedelta(days=30)).isoformat())
        job=make_job(95,1);job.published_at=(reference-timedelta(days=30)).isoformat()
        with patch.object(report,'get_candidate_profile',return_value=PROFILE):
            selected=report.select_jobs([job],evaluation_date=reference)
        self.assertTrue(selected[0].is_excluded)
        self.assertTrue(any('30天' in r for r in selected[0].eligibility_reasons))

    def test_company_intro_and_recommendations_are_not_valid_jd(self):
        self.assertTrue(detail_content_issue('更多职位\n'+'AI解决方案架构师 20-30K 虚构公司\n'*10))
        self.assertTrue(detail_content_issue('公司介绍\n'+'虚构企业技术宣传。'*30))

    def test_rescore_preparation_does_not_replace_published_report(self):
        job=make_job(80,1);job.score_version='v3';job.priority_threshold=82
        storage.save_daily_report('2040-04-01','sample.html',[asdict(job)],[])
        before=storage.get_report_summary('2040-04-01')
        with patch('job_matcher.rescore.get_candidate_profile',return_value=PROFILE),patch('job_matcher.rescore.get_setting',return_value=SAMPLE),patch('job_matcher.rescore._score',return_value=job),patch.object(report,'get_candidate_profile',return_value=PROFILE):
            rescore_saved_report('2040-04-01',self.root/'prepared.json')
        self.assertEqual(storage.get_report_summary('2040-04-01'),before)
