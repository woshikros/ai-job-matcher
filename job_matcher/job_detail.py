from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser


# A bare Mozilla/5.0 is routed to Liepin's device landing page, even for
# public jobs. Keep a complete desktop compatibility identity, not cookies.
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class JobDetailError(RuntimeError):
    def __init__(self, code: str, message: str, *, stop_source: bool = False, browser_allowed: bool = False):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.stop_source = stop_source
        self.browser_allowed = browser_allowed


class _JobIntroParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.collecting = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if not self.collecting and attr_map.get("data-selector") == "job-intro-content":
            self.collecting = True
            self.depth = 1
            return
        if self.collecting:
            if tag in {"br", "hr", "img", "input", "meta", "link"}:
                if tag == "br":
                    self.parts.append("\n")
                return
            self.depth += 1
            if tag in {"p", "li", "div"}:
                self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.collecting:
            return
        self.depth -= 1
        if self.depth == 0:
            self.collecting = False
        elif tag in {"p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.collecting:
            self.parts.append(data)


@dataclass(frozen=True)
class JobDetail:
    text: str
    title: str
    published_at: str = ""


def extract_platform_update_date(raw: str, as_of: date | None = None) -> str:
    reference = as_of or date.today()
    text = html.unescape(str(raw or ""))
    full = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:更新|发布)", text)
    if full:
        try:
            return date(int(full.group(1)), int(full.group(2)), int(full.group(3))).isoformat()
        except ValueError:
            return ""
    short = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:更新|发布)", text)
    if short:
        try:
            candidate = date(reference.year, int(short.group(1)), int(short.group(2)))
            if candidate > reference:
                candidate = date(reference.year - 1, candidate.month, candidate.day)
            return candidate.isoformat()
        except ValueError:
            return ""
    if re.search(r"昨天\s*(?:更新|发布)", text):
        return (reference - timedelta(days=1)).isoformat()
    if re.search(r"(?:今天|刚刚|\d+\s*(?:分钟|小时)前)\s*(?:更新|发布)?", text):
        return reference.isoformat()
    return ""


def fetch_job_detail(url: str, timeout: int = 25) -> JobDetail:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DESKTOP_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            original, destination = urlsplit(url), urlsplit(response.geturl())
            if (destination.hostname != original.hostname or destination.path != original.path
                    or destination.scheme != original.scheme):
                # Do not parse a landing page, login screen or a different job.
                # Only retain public host/path; query strings may contain tokens.
                raise JobDetailError(
                    "DETAIL_REDIRECT",
                    f"详情请求转到了非原岗位页面（{destination.hostname}{destination.path}）；"
                    "已停止本轮猎聘详情读取，请核对官方页面和读取兼容性",
                    stop_source=True,
                    browser_allowed=(destination.scheme == 'https' and destination.hostname == 'wow.liepin.com'
                                     and destination.path == '/t1012695/transit.html'),
                )
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise JobDetailError(
            f"HTTP_{exc.code}", "猎聘详情请求失败；登录或访问限制请在官方页面确认",
            stop_source=exc.code in {401, 403, 429} or exc.code >= 500,
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise JobDetailError("DETAIL_NETWORK_ERROR", "岗位详情网络连接失败或超时") from exc

    parser = _JobIntroParser()
    parser.feed(raw)
    detail = "".join(parser.parts)
    detail = html.unescape(detail).replace("\xa0", " ")
    detail = re.sub(r"[ \t]+", " ", detail)
    detail = re.sub(r"\n\s*\n+", "\n", detail).strip()
    title_match = re.search(r"<title>(.*?)</title>", raw, flags=re.I | re.S)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""
    if len(detail) < 80:
        if re.search(r"安全验证|访问过于频繁|人机验证", raw):
            raise JobDetailError("DETAIL_ACCESS_CHECK", "猎聘要求安全验证；请在官方页面处理", stop_source=True)
        raise JobDetailError("DETAIL_INCOMPLETE", "岗位正文缺失或不足80字，可能下架或页面结构变化")
    return JobDetail(text=detail, title=title, published_at=extract_platform_update_date(raw))
