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

_YEAR_TOKEN = r"(?:\d{1,2}|[一二两三四五六七八九十])"
_AI_TERMS = r"(?:AI|人工智能|大模型|LLM|Agent|智能体|FDE)"
_PRODUCT_TERMS = r"(?:互联网产品|AI产品|产品经理|产品负责人|产品管理|产品规划)"
_SOFTWARE_TERMS = r"(?:软件研发|软件开发|全栈开发|后端开发|前端开发|开发工程师)"

def _year_value(value: str) -> int | None:
    text = str(value or "").strip()
    if text.isdigit(): return int(text)
    return {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(text)

def _required_years(text: str, subject: str) -> int | None:
    patterns = (
        re.compile(rf"(?P<years>{_YEAR_TOKEN})\s*年(?:以上|及以上)?[^。；;\n]{{0,30}}{subject}[^。；;\n]{{0,30}}(?:经验|经历|背景|从业|项目|咨询|实施|研发)", re.I),
        re.compile(rf"{subject}[^。；;\n]{{0,30}}(?P<years>{_YEAR_TOKEN})\s*年(?:以上|及以上)?[^。；;\n]{{0,20}}(?:经验|经历|背景|从业|项目|咨询|实施|研发)", re.I),
    )
    values = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            value = _year_value(match.group("years"))
            if value: values.append(value)
    return max(values) if values else None

def _candidate_ai_years(resume_text: str) -> int | None:
    patterns = (
        re.compile(rf"近\s*(?P<years>{_YEAR_TOKEN})\s*年[^。；;\n]{{0,30}}{_AI_TERMS}", re.I),
        re.compile(rf"(?:从事|负责|聚焦|具备|拥有)[^。；;\n]{{0,15}}{_AI_TERMS}[^。；;\n]{{0,20}}(?P<years>{_YEAR_TOKEN})\s*年", re.I),
    )
    values = []
    for pattern in patterns:
        for match in pattern.finditer(resume_text):
            value = _year_value(match.group("years"))
            if value: values.append(value)
    return max(values) if values else None

_DOMAIN_GROUPS: dict[str, tuple[str, ...]] = {
    "空间智能/IoT/智能建筑": ("空间智能", "iot", "物联网", "智能建筑"),
    "金融": ("金融", "银行", "证券", "保险"),
    "零售": ("零售", "餐饮", "连锁门店"),
    "制造": ("制造", "工业", "工厂"),
    "医疗": ("医疗", "医药", "医院"),
    "半导体/芯片": ("半导体", "芯片", "集成电路"),
    "跨境电商/知识产权": ("跨境电商", "知识产权", "专利", "侵权风控"),
    "供应链": ("供应链", "物流", "库存", "仓储"),
    "建筑/设计": ("建筑", "室内设计", "工程设计"),
}

def _domain_requirements(detail: str) -> list[tuple[str, int | None]]:
    found = []
    for label, terms in _DOMAIN_GROUPS.items():
        blob = "|".join(re.escape(term) for term in terms)
        years = _required_years(detail, rf"(?:{blob})")
        explicit = re.search(rf"(?:具备|要求|需要|拥有)[^。；;\n]{{0,35}}(?:{blob})[^。；;\n]{{0,18}}(?:深耕|经验|背景|从业)", detail, re.I)
        if years or explicit: found.append((label, years))
    return found

def clean_job_text(value: Any, maximum: int = MAX_JOB_TEXT_LENGTH) -> SafeJobText:
    raw = unicodedata.normalize("NFKC", html.unescape(str(value or ""))); warnings: list[str] = []
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

def evaluate_eligibility(
    resume_text: str, job: dict[str, Any], detail: str, deadline_status: str,
    target_city: str | Iterable[str] = "深圳", excluded_keywords: Iterable[str] | None = None,
    strict_matching: bool = True, exclude_staffing_agencies: bool = True,
) -> EligibilityResult:
    resume_text = unicodedata.normalize("NFKC", str(resume_text or ""))
    detail = unicodedata.normalize("NFKC", str(detail or ""))
    resume_lower, detail_lower, failures, flags = resume_text.lower(), detail.lower(), [], []
    outsourcing_reason = detect_outsourcing(job, detail, exclude_staffing_agencies=exclude_staffing_agencies)
    if outsourcing_reason: failures.append(f"明确外包：{outsourcing_reason}")
    education = str(job.get("education") or job.get("jobDegree") or "")
    if ("博士" in education or re.search(r"博士(?:学历|及以上|以上)", detail)) and "博士" not in resume_text: failures.append("明确要求博士学历，简历没有相应证据")
    elif ("硕士" in education or re.search(r"硕士(?:学历|及以上|以上)", detail)) and not any(x in resume_text for x in ("硕士", "博士")): failures.append("明确要求硕士及以上学历，简历没有相应证据")
    for language in ("python", "java", "golang", "c++"):
        if re.search(rf"(?:精通|熟练|必须掌握|硬性要求|熟悉).{{0,16}}{re.escape(language)}", detail_lower) and language not in resume_lower: failures.append(f"明确要求熟练掌握{language}，简历没有相应证据")
        elif strict_matching and re.search(rf"(?:具备|掌握|要求).{{0,16}}{re.escape(language)}|{re.escape(language)}.{{0,12}}(?:基础|能力|经验)", detail_lower) and language not in resume_lower: flags.append(f"岗位要求{language}基础能力，简历没有明确证据")
    if strict_matching:
        ai_required = _required_years(detail, _AI_TERMS); candidate_ai = _candidate_ai_years(resume_text)
        if ai_required:
            if candidate_ai is None: flags.append(f"明确要求{ai_required}年以上AI相关经验，简历中的AI年限需要确认")
            elif ai_required - candidate_ai >= 2: failures.append(f"明确要求{ai_required}年以上AI相关经验，简历仅有约{candidate_ai}年明确证据")
            elif ai_required > candidate_ai: flags.append(f"AI相关经验要求{ai_required}年以上，简历仅有约{candidate_ai}年明确证据")
        product_required = _required_years(detail, _PRODUCT_TERMS)
        if product_required and not re.search(r"产品经理|产品负责人|产品总监|产品甲方", resume_text, re.I): flags.append(f"明确要求{product_required}年以上正式产品经验，简历缺少对应职位证据")
        software_required = _required_years(detail, _SOFTWARE_TERMS)
        software_evidence = re.search(r"软件工程师|开发工程师|全栈工程师|后端工程师|前端工程师|软件研发", resume_text, re.I)
        if software_required and not software_evidence: failures.append(f"明确要求{software_required}年以上软件研发经验，简历没有对应职位证据")
        if re.search(r"全栈(?:工程|开发)能力|独立(?:完成|负责).{0,18}(?:前后端|生产系统|核心代码)", detail, re.I) and not software_evidence: failures.append("明确要求全栈或生产级软件工程能力，简历没有对应证据")
        technical_engineering_signals = (
            bool(re.search(r"模型训练|模型微调|训练调参|特征工程|强化学习", detail, re.I)),
            bool(re.search(r"mlops|gpu集群|分布式训练|模型仓库|特征平台", detail, re.I)),
            bool(re.search(r"核心代码|代码审查|AI平台.{0,12}(?:开发|维护)|推理平台.{0,12}(?:开发|维护)", detail, re.I)),
            bool(re.search(r"推理服务|grpc|保障sla|性能压测|吞吐和延迟", detail, re.I)),
        )
        if sum(technical_engineering_signals) >= 2 and not software_evidence: failures.append("岗位核心为AI平台、模型训练或推理工程，简历没有生产研发背景")
        for domain_label, required_years in _domain_requirements(detail):
            terms = _DOMAIN_GROUPS[domain_label]
            if any(term.lower() in resume_lower for term in terms): continue
            if required_years and required_years >= 3: failures.append(f"明确要求{required_years}年以上{domain_label}经验，简历没有对应行业证据")
            else: flags.append(f"岗位要求{domain_label}深耕经验，简历证据需要确认")
    embedded_terms = ("mcu", "rtos", "freertos", "rt-thread", "cortex-m", "bootloader", "驱动开发")
    if any(term in detail_lower for term in embedded_terms) and not any(term in resume_lower for term in embedded_terms): failures.append("明确要求嵌入式系统开发能力，简历没有相应证据")
    for keyword in excluded_keywords or []:
        if str(keyword).strip() and str(keyword).lower() in f"{job.get('jobName', '')} {detail}".lower(): failures.append(f"命中不考虑关键词：{str(keyword).strip()}")
    location = str(job.get("location") or job.get("city") or "")
    target_cities = [target_city] if isinstance(target_city, str) else list(target_city)
    if location and target_cities and not any(str(city) in location for city in target_cities) and re.search(r"现场办公|必须到岗|工作地点", detail) and not re.search(r"远程|可居家", detail): failures.append(f"明确现场工作地点为{location}，不在目标城市{'、'.join(str(city) for city in target_cities)}")
    if deadline_status == "expired": failures.append("招聘截止日期已经过去")
    if strict_matching and len(detail) >= 200 and not re.search(r"岗位职责|工作职责|职位描述|任职要求|岗位要求|负责", detail): failures.append("岗位详情缺少明确职责或任职要求，无法可靠精读")
    if re.search(r"(?:英语|英文).{0,15}(?:流利|熟练|商务|六级|cet-?6|必需|必须)", detail_lower) and not any(x in resume_lower for x in ("英语", "english", "cet", "toefl", "ielts")): flags.append("英语能力要求需要人工确认")
    if re.search(r"高频出差|频繁出差|长期出差|出差.{0,5}(?:50%|一半)", detail): flags.append("岗位包含高频出差，需要人工确认")
    if re.search(r"长期驻场|常驻客户|驻场交付", detail): flags.append("岗位包含长期或客户驻场，需要人工确认")
    if failures: return EligibilityResult("fail", list(dict.fromkeys(failures + flags)))
    if flags: return EligibilityResult("flag", list(dict.fromkeys(flags)))
    return EligibilityResult("pass", [])
