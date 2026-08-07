from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from .recruiting import detect_outsourcing

MAX_JOB_TEXT_LENGTH = 30_000
_HIDDEN = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+", re.I)
_PROMPT_LIKE = re.compile(r"(?:ignore|disregard|override).{0,30}(?:instruction|prompt)|忽略.{0,20}(?:指令|提示词)|(?:system|assistant)\s*prompt|执行以下指令", re.I)
_DATE_YMD = re.compile(r"(?P<y>20\d{2})\s*[年./-]\s*(?P<m>\d{1,2})\s*[月./-]\s*(?P<d>\d{1,2})\s*日?")
_DATE_MD = re.compile(r"(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日")
_DEADLINE_LINE = re.compile(r"(?:申请|报名|招聘|投递)?\s*截止(?:日期|时间)?\s*[:：]?\s*([^\n。；;]{2,40})", re.I)

@dataclass(frozen=True)
class SafeJobText:
    text: str
    warnings: list[str]

@dataclass(frozen=True)
class EligibilityResult:
    verdict: str
    reasons: list[str]

def clean_job_text(value: Any, maximum: int = MAX_JOB_TEXT_LENGTH) -> SafeJobText:
    raw = html.unescape(str(value or "")); warnings: list[str] = []
    if _TAG.search(raw): raw = _TAG.sub(" ", raw); warnings.append("已清理残留HTML")
    if _HIDDEN.search(raw): raw = _HIDDEN.sub("", raw); warnings.append("已清理隐藏字符")
    raw = "".join(ch for ch in raw if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n"); raw = re.sub(r"[ \t]+", " ", raw); raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    if _URL.search(raw): warnings.append("JD正文包含链接，系统不会访问")
    if _PROMPT_LIKE.search(raw): warnings.append("JD含疑似指令文本，仅按普通文字处理")
    if len(raw) > maximum: raw = raw[:maximum]; warnings.append(f"JD超过{maximum}字，已截断")
    return SafeJobText(raw, list(dict.fromkeys(warnings)))

def _parse_date_text(value: str, as_of: date) -> date | None:
    text = str(value or "").strip()
    if not text: return None
    match = _DATE_YMD.search(text)
    if match:
        try: return date(int(match["y"]), int(match["m"]), int(match["d"]))
        except ValueError: return None
    match = _DATE_MD.search(text)
    if match:
        try:
            candidate = date(as_of.year, int(match["m"]), int(match["d"]))
            return date(as_of.year + 1, candidate.month, candidate.day) if candidate < as_of and (as_of - candidate).days > 180 else candidate
        except ValueError: return None
    try: return datetime.fromisoformat(text[:10]).date()
    except ValueError: return None

def extract_deadline(structured: Any, detail: str, as_of: date | None = None) -> str:
    reference = as_of or date.today(); parsed = _parse_date_text(str(structured or ""), reference)
    if parsed: return parsed.isoformat()
    match = _DEADLINE_LINE.search(detail)
    if not match: return ""
    parsed = _parse_date_text(match.group(1), reference); return parsed.isoformat() if parsed else ""

def posting_status(deadline: str, as_of: date | None = None) -> str:
    if not deadline: return "unknown"
    reference = as_of or date.today()
    try: value = date.fromisoformat(deadline)
    except ValueError: return "unknown"
    days = (value - reference).days
    return "expired" if days < 0 else "closing_soon" if days <= 7 else "active"

def evaluate_eligibility(resume_text: str, job: dict[str, Any], detail: str, deadline_status: str, target_city: str | Iterable[str] = "深圳", excluded_keywords: Iterable[str] | None = None) -> EligibilityResult:
    resume_lower, detail_lower, failures, flags = resume_text.lower(), detail.lower(), [], []
    outsourcing_reason = detect_outsourcing(job, detail)
    if outsourcing_reason: failures.append(f"明确外包：{outsourcing_reason}")
    education = str(job.get("education") or job.get("jobDegree") or "")
    if ("博士" in education or re.search(r"博士(?:学历|及以上|以上)", detail)) and "博士" not in resume_text: failures.append("明确要求博士学历，简历没有相应证据")
    elif ("硕士" in education or re.search(r"硕士(?:学历|及以上|以上)", detail)) and not any(x in resume_text for x in ("硕士", "博士")): failures.append("明确要求硕士及以上学历，简历没有相应证据")
    for language in ("python", "java", "golang", "c++"):
        if re.search(rf"(?:精通|熟练|必须掌握|硬性要求|熟悉).{{0,16}}{re.escape(language)}", detail_lower) and language not in resume_lower: failures.append(f"明确要求熟练掌握{language}，简历没有相应证据")
    embedded_terms = ("mcu", "rtos", "freertos", "rt-thread", "cortex-m", "bootloader", "驱动开发")
    if any(term in detail_lower for term in embedded_terms) and not any(term in resume_lower for term in embedded_terms): failures.append("明确要求嵌入式系统开发能力，简历没有相应证据")
    for keyword in excluded_keywords or []:
        if str(keyword).strip() and str(keyword).lower() in f"{job.get('jobName', '')} {detail}".lower(): failures.append(f"命中不考虑关键词：{str(keyword).strip()}")
    location = str(job.get("location") or job.get("city") or "")
    target_cities = [target_city] if isinstance(target_city, str) else list(target_city)
    if location and target_cities and not any(str(city) in location for city in target_cities) and re.search(r"现场办公|必须到岗|工作地点", detail) and not re.search(r"远程|可居家", detail): failures.append(f"明确现场工作地点为{location}，不在目标城市{'、'.join(str(city) for city in target_cities)}")
    if deadline_status == "expired": failures.append("招聘截止日期已经过去")
    if re.search(r"(?:英语|英文).{0,15}(?:流利|熟练|商务|六级|cet-?6|必需|必须)", detail_lower) and not any(x in resume_lower for x in ("英语", "english", "cet", "toefl", "ielts")): flags.append("英语能力要求需要人工确认")
    if re.search(r"高频出差|频繁出差|长期出差|出差.{0,5}(?:50%|一半)", detail): flags.append("岗位包含高频出差，需要人工确认")
    if re.search(r"长期驻场|常驻客户|驻场交付", detail): flags.append("岗位包含长期或客户驻场，需要人工确认")
    if failures: return EligibilityResult("fail", list(dict.fromkeys(failures + flags)))
    if flags: return EligibilityResult("flag", list(dict.fromkeys(flags)))
    return EligibilityResult("pass", [])
