from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


CITY_CODES = {"深圳": "765"}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138 Safari/537.36"


class ZhilianReadError(RuntimeError):
    def __init__(self, message: str, code: str = "ZHILIAN_READ_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ZhilianDetail:
    text: str
    url: str
    raw: dict[str, Any]


def _fetch_text(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ZhilianReadError(f"智联页面返回HTTP {response.status}", "HTTP_ERROR")
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ZhilianReadError(f"智联页面返回HTTP {exc.code}", "HTTP_ERROR") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ZhilianReadError(f"智联页面读取失败：{exc}", "NETWORK_ERROR") from exc


def _extract_state(page: str) -> dict[str, Any]:
    marker = "__INITIAL_STATE__="
    if marker not in page:
        raise ZhilianReadError("智联页面缺少结构化岗位数据", "PAGE_CHANGED")
    try:
        state, _ = json.JSONDecoder().raw_decode(page.split(marker, 1)[1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise ZhilianReadError("智联岗位数据无法解析", "PAGE_CHANGED") from exc
    if not isinstance(state, dict):
        raise ZhilianReadError("智联岗位数据格式异常", "PAGE_CHANGED")
    if state.get("isVerification"):
        raise ZhilianReadError("智联要求安全验证，已停止读取", "SECURITY_CHECK")
    return state


def _clean_html(value: str) -> str:
    text = re.sub(r"</?(?:div|p|li|br|h\d)[^>]*>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _position_base(item: dict[str, Any]) -> dict[str, Any]:
    return (((item.get("jobDetailData") or {}).get("position") or {}).get("base") or {})


def _embedded_detail(item: dict[str, Any]) -> str:
    description = (((item.get("jobDetailData") or {}).get("position") or {}).get("desc") or {}).get("description") or ""
    return _clean_html(str(description))


def normalise_zhilian_job(item: dict[str, Any]) -> dict[str, Any]:
    base = _position_base(item)
    raw_id = str(base.get("positionNumber") or item.get("positionNumber") or "")
    if not raw_id:
        raise ZhilianReadError("智联岗位缺少岗位编号", "JOB_NOT_FOUND")
    location = "·".join(part for part in ("深圳", str(item.get("cityDistrict") or "")) if part)
    detail_url = f"https://www.zhaopin.com/jobdetail/{raw_id}.htm"
    return {
        "source": "zhilian",
        "sourceJobId": raw_id,
        "jobId": f"zhilian:{raw_id}",
        "jobName": str(base.get("positionName") or item.get("name") or ""),
        "company": str(item.get("companyName") or ""),
        "location": location,
        "salary": str(base.get("salary") or item.get("salary60") or ""),
        "education": str(base.get("education") or item.get("education") or ""),
        "workYears": str(base.get("positionWorkingExp") or item.get("workingExp") or ""),
        "industry": str(item.get("industryName") or ""),
        "jobDetailUrl": detail_url,
        "embeddedDetail": _embedded_detail(item),
        "raw": item,
    }


def search_zhilian_jobs(query: str, city: str = "深圳", page: int = 1) -> list[dict[str, Any]]:
    city_code = CITY_CODES.get(city)
    if not city_code:
        raise ZhilianReadError(f"暂不支持智联城市：{city}", "UNSUPPORTED_CITY")
    url = "https://sou.zhaopin.com/?" + urllib.parse.urlencode({"jl": city_code, "kw": query, "p": page})
    state = _extract_state(_fetch_text(url))
    rows = state.get("positionList") or []
    if not isinstance(rows, list):
        raise ZhilianReadError("智联搜索结果格式异常", "PAGE_CHANGED")
    jobs = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("cityId") or "") != city_code:
            continue
        try:
            jobs.append(normalise_zhilian_job(row))
        except ZhilianReadError:
            continue
    return jobs


def fetch_zhilian_detail(job: dict[str, Any]) -> ZhilianDetail:
    raw_id = str(job.get("sourceJobId") or "")
    url = str(job.get("jobDetailUrl") or f"https://www.zhaopin.com/jobdetail/{raw_id}.htm")
    if not raw_id:
        raise ZhilianReadError("智联岗位缺少详情编号", "JOB_NOT_FOUND")
    state = _extract_state(_fetch_text(url))
    position = (state.get("jobDetail") or {}).get("detailedPosition") or {}
    if not isinstance(position, dict):
        raise ZhilianReadError("智联岗位详情为空", "JOB_NOT_FOUND")
    detail = _clean_html(str(position.get("jobDesc") or position.get("description") or ""))
    if len(detail) < 80:
        raise ZhilianReadError("智联岗位详情内容不完整", "JOB_DETAIL_INCOMPLETE")
    return ZhilianDetail(text=detail, url=url, raw=position)
