import unittest
from unittest.mock import Mock, patch
from job_matcher.job_detail import JobDetail, JobDetailError


class LiepinReaderTests(unittest.TestCase):
    def test_known_device_redirect_uses_browser_and_stays_on_that_path(self):
        from job_matcher.liepin_reader import LiepinReader
        direct = Mock(side_effect=JobDetailError('DETAIL_REDIRECT', 'landing', stop_source=True, browser_allowed=True))
        browser = Mock(return_value=JobDetail('真实正文' * 30, '岗位'))
        reader = LiepinReader(direct, browser)
        self.assertEqual(reader('one').text, '真实正文' * 30)
        self.assertEqual(reader('two').text, '真实正文' * 30)
        direct.assert_called_once_with('one')
        self.assertEqual(browser.call_count, 2)

    def test_security_errors_never_trigger_browser_retry(self):
        from job_matcher.liepin_reader import LiepinReader
        for code in ['HTTP_401', 'HTTP_403', 'HTTP_429', 'DETAIL_ACCESS_CHECK', 'DETAIL_REDIRECT']:
            direct = Mock(side_effect=JobDetailError(code, 'blocked', stop_source=True))
            browser = Mock()
            with self.assertRaises(JobDetailError):
                LiepinReader(direct, browser)('url')
            browser.assert_not_called()

    def test_network_reads_are_spaced_but_cache_hits_are_not(self):
        from job_matcher.liepin_reader import LiepinReader
        from job_matcher.daily_cache import CachedReads
        from pathlib import Path
        import tempfile
        now = [0.0]
        starts = []
        def sleep(seconds): now[0] += seconds
        def direct(url):
            starts.append(now[0])
            return {'text': url}
        with tempfile.TemporaryDirectory() as temp, patch('job_matcher.liepin_reader.time.monotonic', side_effect=lambda: now[0]), patch('job_matcher.liepin_reader.time.sleep', side_effect=sleep):
            reader = LiepinReader(direct, Mock())
            cache = CachedReads(Path(temp) / 'cache.json')
            for key in ['one', 'one', 'two']:
                cache.call(key, lambda: reader(key))
            self.assertEqual(starts, [0.0, 2.0])

    def test_browser_rejects_wrong_job_and_login(self):
        from job_matcher.liepin_reader import fetch_browser_detail
        url = 'https://www.liepin.com/job/123.shtml'
        for payload in [{'url': 'https://www.liepin.com/job/999.shtml', 'description': '描述' * 100},
                        {'url': url, 'description': '描述' * 100, 'login_required': True},
                        {'url': url, 'description': '描述' * 100, 'security_check': True}]:
            with patch('job_matcher.liepin_reader._extension_command', return_value=payload), self.assertRaises(JobDetailError):
                fetch_browser_detail(url)

    def test_browser_full_jd_preserves_update_date(self):
        from job_matcher.liepin_reader import fetch_browser_detail
        url = 'https://www.liepin.com/job/123.shtml'
        with patch('job_matcher.liepin_reader._extension_command', return_value={'url':url, 'description':'真实职责' * 30, 'title':'岗位', 'update_text':'2026年9月11日更新'}):
            result = fetch_browser_detail(url)
        self.assertEqual(result.published_at, '2026-09-11')

    def test_each_detail_failure_records_job_not_only_total(self):
        from job_matcher.liepin_details import read_details
        events = []
        def read(job): raise JobDetailError('DETAIL_ACCESS_CHECK', '验证', stop_source=True)
        result = read_details([{'jobId':'liepin:123'}, {'jobId':'liepin:456'}], read, on_result=events.append)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(events[0]['job_id'], 'liepin:123')
        self.assertEqual(events[0]['code'], 'DETAIL_ACCESS_CHECK')
