import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from job_matcher import job_detail


class Response(io.BytesIO):
    def __init__(self, body, url):
        super().__init__(body.encode('utf-8'))
        self.url = url

    def geturl(self):
        return self.url


class LiepinDetailRecoveryTests(unittest.TestCase):
    url = 'https://www.liepin.com/a/12345678.shtml'

    def test_desktop_request_gets_job_instead_of_device_landing_page(self):
        detail = '负责企业智能体方案及业务交付。' * 20
        def site(request, timeout):
            user_agent = request.get_header('User-agent', '')
            if 'Windows NT' in user_agent and 'AppleWebKit/' in user_agent and 'Chrome/' in user_agent:
                return Response('<dd data-selector="job-intro-content">' + detail + '</dd>', self.url)
            return Response('<script>location.href=pcUrl</script>',
                            'https://wow.liepin.com/t1012695/transit.html')
        with patch.object(job_detail.urllib.request, 'urlopen', side_effect=site):
            self.assertEqual(job_detail.fetch_job_detail(self.url).text, detail)

    def test_http_200_transit_page_is_source_error_not_empty_job(self):
        response = Response('<script>location.href=pcUrl</script>',
                            'https://wow.liepin.com/t1012695/transit.html')
        with patch.object(job_detail.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'DETAIL_REDIRECT') as error:
                job_detail.fetch_job_detail(self.url)
        self.assertTrue(error.exception.stop_source)

    def test_wrong_job_redirect_cannot_be_scored_as_requested_job(self):
        response = Response('<dd data-selector="job-intro-content">' + '其他岗位职责。' * 30 + '</dd>',
                            'https://www.liepin.com/a/99999999.shtml')
        with patch.object(job_detail.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'DETAIL_REDIRECT'):
                job_detail.fetch_job_detail(self.url)

    def test_normal_job_page_still_parses_full_description(self):
        detail = '负责企业需求分析和智能体应用交付。' * 20
        response = Response('<title>测试职位</title><dd data-selector="job-intro-content">' + detail + '</dd>', self.url)
        with patch.object(job_detail.urllib.request, 'urlopen', return_value=response):
            self.assertEqual(job_detail.fetch_job_detail(self.url).text, detail)

    def test_access_limit_preserves_actionable_code_without_response_body(self):
        for status in (401, 403, 429):
            with self.subTest(status=status), patch.object(job_detail.urllib.request, 'urlopen',
                    side_effect=HTTPError(self.url, status, 'private data', {}, None)):
                with self.assertRaisesRegex(RuntimeError, str(status)) as error:
                    job_detail.fetch_job_detail(self.url)
                self.assertTrue(error.exception.stop_source)
                self.assertNotIn('private data', str(error.exception))

    def test_transit_failure_stops_before_other_119_jobs(self):
        from job_matcher.liepin_details import read_details
        calls = []
        def read(job):
            calls.append(job)
            raise job_detail.JobDetailError('DETAIL_REDIRECT', '跳转页', stop_source=True)
        result = read_details(list(range(120)), read)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.skipped, 119)
        self.assertIn('DETAIL_REDIRECT', result.reason)

    def test_repeated_incomplete_details_stop_bounded_batch(self):
        from job_matcher.liepin_details import read_details
        calls = []
        def read(job):
            calls.append(job)
            raise RuntimeError('岗位详情内容不完整')
        result = read_details(list(range(120)), read)
        self.assertLessEqual(len(calls), 6)
        self.assertGreater(result.skipped, 0)
        self.assertIn('岗位详情内容不完整', result.reason)

    def test_one_expired_job_does_not_discard_successes(self):
        from job_matcher.liepin_details import read_details
        def read(job):
            if job == 2:
                raise RuntimeError('岗位已下架')
            return {'text': str(job)}
        result = read_details(list(range(8)), read)
        self.assertEqual([job for job, _ in result.completed], [0, 1, 3, 4, 5, 6, 7])
        self.assertEqual(result.failures, 1)
        self.assertEqual(result.skipped, 0)

    def test_partial_success_retained_when_later_batch_is_blocked(self):
        from job_matcher.liepin_details import read_details
        def read(job):
            if job:
                raise job_detail.JobDetailError('HTTP_429', '访问受限', stop_source=True)
            return {'text': '完整JD'}
        result = read_details(list(range(120)), read)
        self.assertEqual(result.completed, [(0, {'text': '完整JD'})])
        self.assertEqual(result.skipped, 118)
