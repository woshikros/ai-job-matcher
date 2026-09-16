import unittest
from datetime import date
from inspect import signature
from unittest.mock import patch
from job_matcher import daily_report as report

class ReportDateRegression(unittest.TestCase):
    def test_historical_source_failure_uses_report_date(self):
        with patch.object(report, 'get_candidate_profile', return_value={'cities':['示例城市']}), patch.object(report, 'profile_queries', return_value=['AI']), patch.object(report, 'get_setting', side_effect=lambda key, default=None: 'resume' if key=='resume_text' else 20000), patch.object(report, 'get_excluded_identities', return_value=(set(),set())), patch.object(report, 'collect_liepin_candidates', return_value=[]), patch.object(report, 'CachedReads'), patch.object(report, 'get_source_health', return_value={'enabled':True}), patch.object(report, 'search_zhilian_jobs', side_effect=report.ZhilianReadError('offline','NETWORK_ERROR')), patch.object(report, 'save_skill_observations'), patch.object(report, 'record_source_validation') as record:
            kwargs={'report_date_value':date(2020,1,2)}
            if 'include_boss' in signature(report.collect_report_jobs).parameters: kwargs.update(include_boss=False,include_liepin=False)
            report.collect_report_jobs(**kwargs)
            self.assertEqual(record.call_args.args[:2], ('zhilian','2020-01-02'))
