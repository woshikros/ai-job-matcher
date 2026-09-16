"""CLI search is unchanged; render normal pages only for a known device redirect."""
import time
from urllib.parse import urlsplit

from .liepin_bridge import _extension_command, LiepinBridgeError
from .job_detail import JobDetail, JobDetailError, extract_platform_update_date


def fetch_browser_detail(url: str) -> JobDetail:
    expected = urlsplit(url)
    import re
    if expected.scheme != 'https' or expected.hostname != 'www.liepin.com' or not re.fullmatch(r'/(?:job|a)/\d+\.shtml', expected.path):
        raise JobDetailError('DETAIL_URL_BLOCKED', '仅允许读取猎聘岗位详情链接', stop_source=True)
    try:
        data = _extension_command('extract_liepin_detail', url, wait_for_extension=2)
    except LiepinBridgeError as exc:
        raise JobDetailError('DETAIL_BROWSER_UNAVAILABLE', str(exc), stop_source=True) from exc
    if data.get('security_check') or data.get('environment_risk'):
        raise JobDetailError('DETAIL_ACCESS_CHECK', '猎聘页面提示验证或访问异常，请在官方页面处理', stop_source=True)
    if data.get('login_required'):
        raise JobDetailError('DETAIL_LOGIN_REQUIRED', '请在Chrome中登录猎聘', stop_source=True)
    actual = urlsplit(str(data.get('url') or ''))
    if (actual.scheme, actual.hostname, actual.path) != (expected.scheme, expected.hostname, expected.path):
        raise JobDetailError('DETAIL_BROWSER_REDIRECT', '正常浏览器仍未到达原岗位，已停止读取', stop_source=True)
    text = str(data.get('description') or '').strip()
    if len(text) < 80:
        raise JobDetailError('DETAIL_INCOMPLETE', '浏览器岗位正文不足80字或岗位已下架')
    return JobDetail(text, str(data.get('title') or ''), extract_platform_update_date(str(data.get('update_text') or '')))


class LiepinReader:
    def __init__(self, direct, browser=fetch_browser_detail):
        self.direct = direct
        self.browser = browser
        self.mode = 'direct'
        self.next_start = 0.0

    def _read(self, callback, url):
        delay = self.next_start - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        try:
            return callback(url)
        finally:
            self.next_start = time.monotonic() + 2.0

    def __call__(self, url):
        if self.mode == 'browser':
            return self._read(self.browser, url)
        try:
            return self._read(self.direct, url)
        except JobDetailError as exc:
            # Never switch paths for 401/403/429 or a security challenge.
            if not exc.browser_allowed:
                raise
            self.mode = 'browser'
            return self._read(self.browser, url)
