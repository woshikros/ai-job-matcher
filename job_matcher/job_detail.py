from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser


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


def fetch_job_detail(url: str, timeout: int = 25) -> JobDetail:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"岗位详情读取失败：{url}") from exc

    parser = _JobIntroParser()
    parser.feed(raw)
    detail = "".join(parser.parts)
    detail = html.unescape(detail).replace("\xa0", " ")
    detail = re.sub(r"[ \t]+", " ", detail)
    detail = re.sub(r"\n\s*\n+", "\n", detail).strip()
    title_match = re.search(r"<title>(.*?)</title>", raw, flags=re.I | re.S)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""
    if len(detail) < 80:
        raise RuntimeError(f"岗位详情内容不完整：{url}")
    return JobDetail(text=detail, title=title)
