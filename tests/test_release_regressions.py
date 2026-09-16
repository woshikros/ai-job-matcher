import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_daily_report import make_job
from job_matcher import daily_report as report
from job_matcher.cli_client import LiepinCliError


class ReleaseRegressions(unittest.TestCase):
    def test_render_preserves_failed_source_in_html_and_history(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(report, 'get_source_health', side_effect=lambda source: {'source':source, 'status':'failed', 'enabled':False, 'error':'sample source unavailable'}), patch.object(report, 'save_daily_report') as save:
            output = Path(tmp) / 'report.html'
            report.render_report([], {}, output, '2020-01-02')
            states = save.call_args.args[3]
            self.assertEqual(next(s for s in states if s['source']=='liepin')['status'], 'failed')
            self.assertIn('sample source unavailable', output.read_text(encoding='utf-8'))

    def test_recruiter_replacements_do_not_exceed_cautious_quota(self):
        jobs = [make_job(90, n) for n in range(3)] + [make_job(80, n + 10) for n in range(12)]
        for job in jobs:
            job.recruiter_type = 'headhunter' if job.score == 90 else 'employer'
        selected = report.select_jobs(jobs, threshold=82, consider_threshold=75, minimum_high=15, fallback_count=5, max_headhunter_share=20, headhunter_free_top_n=3)
        self.assertLessEqual(sum(j.is_supplemental for j in selected), 5)
        self.assertLessEqual(sum(j.recruiter_type == 'headhunter' for j in selected) * 5, len(selected))

    def test_failed_liepin_search_does_not_prevent_next_source(self):
        with patch.object(report, 'get_candidate_profile', return_value={'cities':['示例城市']}), patch.object(report, 'profile_queries', return_value=['AI应用']), patch.object(report, 'get_setting', return_value='示例简历'), patch.object(report, 'get_excluded_identities', return_value=(set(),set())), patch.object(report, 'collect_liepin_candidates', side_effect=LiepinCliError('offline')), patch.object(report, 'get_source_health', return_value={'enabled':False}) as health, patch.object(report, 'save_skill_observations'), patch.object(report, 'record_source_validation'):
            report.collect_report_jobs()
            health.assert_called_with('zhilian')

    def test_release_scan_catches_force_added_ignored_private_files(self):
        tool = Path(__file__).parents[1] / 'tools/security_checks.py'
        spec = importlib.util.spec_from_file_location('release_checks', tool)
        checks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checks)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.gitignore').write_text('\n'.join(checks.REQUIRED_IGNORES), encoding='utf-8')
            (root / 'data').mkdir()
            (root / 'data/private.db').write_bytes(b'test-private-database')
            subprocess.run(['git','init','-q',str(root)], check=True, capture_output=True)
            subprocess.run(['git','-C',str(root),'add','-f','data/private.db'], check=True, capture_output=True)
            with patch.object(checks, 'ROOT', root):
                errors = checks.run_checks(release=True)
            self.assertTrue(any('data/private.db' in e for e in errors), errors)
