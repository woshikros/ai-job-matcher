from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from .recruiting import detect_outsourcing
from .job_detail import extract_platform_update_date

MAX_JOB_TEXT_LENGTH = 30_000
MAX_JOB_UPDATE_AGE_DAYS = 30


def stale_update_reason(value: Any, as_of: date | None = None, max_age_days: int = MAX_JOB_UPDATE_AGE_DAYS) -> str:
    from datetime import timedelta, timezone
    reference = as_of or datetime.now(timezone(timedelta(hours=8))).date()
    normalized = extract_platform_update_date(str(value or ''), reference)
    if not normalized:
        return ''
    age = (reference - date.fromisoformat(normalized)).days
    if max_age_days > 0 and age >= max_age_days:
        return f'平台最后更新于{normalized}，距报告日期{age}天，达到{max_age_days}天排除线'
    return ''
_HIDDEN = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+", re.I)
_PROMPT_LIKE = re.compile(
    r"(?:ignore|disregard|override).{0,30}(?:instruction|prompt)|忽略.{0,20}(?:指令|提示词)|"
    r"(?:system|assistant)\s*prompt|执行以下指令",
    re.I,
)
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


_YEAR_TOKEN = r"(?<!\d)(?:\d{1,2}|[一二两三四五六七八九十])(?!\d)"
_AI_TERMS = r"(?:AI|人工智能|大模型|LLM|Agent|智能体|FDE)"
_PRODUCT_TERMS = r"(?:互联网产品|AI产品|产品经理|产品负责人|产品管理|产品规划|B端产品|产品)"
_SOFTWARE_TERMS = r"(?:软件研发|软件开发|全栈开发|后端开发|前端开发|开发工程师)"

_ROLE_HEADING = re.compile(r"^(?:岗位目标|岗位职责|工作职责|核心职责|主要职责|核心职能|具体工作内容|岗位定位|岗位使命|职位概述|职位描述|职责描述|工作内容|你将负责|你要负责|任职要求|岗位要求|任职资格|职位要求|我们希望你|关键能力要求|Responsibilities|Qualifications)", re.I)
_COMPANY_HEADING = re.compile(r"^(?:公司介绍|公司简介|企业简介|关于我们|关于公司|关于\s*[A-Za-z]|关于深度)", re.I)


def role_content(detail: str) -> str:
    """Keep job duties/requirements; company marketing is not role evidence."""
    text = re.sub(r"(?<!\n)(?=【(?:岗位|任职|职位|关于|公司|企业))", "\n", str(detail or ""))
    lines, in_company = [], False
    for line in text.splitlines():
        heading = re.sub(r"^[\s*#【]+", "", line)
        heading = re.sub(r"^\d+[、.)）]\s*", "", heading)
        if _COMPANY_HEADING.match(heading):
            in_company = True
        elif _ROLE_HEADING.match(heading):
            in_company = False
        if not in_company:
            lines.append(line)
    return "\n".join(lines).strip()


def _mandatory_clauses(detail: str) -> str:
    clauses, optional = [], False
    optional_item = False
    for line in role_content(detail).splitlines():
        heading = re.sub(r"^[\s*#【]+", "", line)
        numbered = bool(re.match(r'^\d+[、.)）]\s*', heading))
        heading = re.sub(r'^\d+[、.)）]\s*', '', heading)
        if optional_item and numbered:
            optional = False
            optional_item = False
        if re.match(r"^(?:加分项|优先条件|优先考虑)", heading):
            optional = True
            optional_item = numbered
        elif _ROLE_HEADING.match(heading):
            optional = False
        if optional:
            continue
        for clause in re.split(r"[。；;，,]", line):
            if not re.search(r"优先|加分|非必[须需]|无需|不要求|不需要", clause):
                clauses.append(clause)
    return "\n".join(clauses)


def location_matches_city(location: str, cities: Iterable[str]) -> bool:
    if any(str(city) in location for city in cities):
        return True
    shenzhen_districts = ('福田区', '罗湖区', '南山区', '宝安区', '龙岗区', '盐田区', '龙华区', '坪山区', '光明区', '大鹏新区', '深汕特别合作区')
    return '深圳' in cities and any(district in location for district in shenzhen_districts)


def has_term(text: str, term: str) -> bool:
    return bool(re.search(r'(?<![a-z0-9])' + re.escape(term.lower()) + r'(?![a-z0-9])', text.lower())) if re.search(r'[a-z]', term.lower()) else term in text


def detail_content_issue(detail: str) -> str:
    role = role_content(unicodedata.normalize('NFKC', str(detail or '')))
    if len(str(detail or '').strip()) < 80:
        return '岗位详情正文不足80字'
    substance = re.search(r'岗位职责|工作职责|职位描述|任职要求|岗位要求|任职资格|职位要求|关键能力要求|工作内容|职责描述|你将负责|负责(?!人)|(?:具备|掌握|熟悉).{0,20}(?:经验|能力|技术)', role)
    if (len(detail) >= 200 or re.search(r'精选职位|推荐职位|猜你喜欢|更多职位|看过该职位', detail)) and not substance:
        return '岗位详情缺少明确职责或任职要求，可能仅为推荐职位列表，无法可靠精读'
    return ''


def _engineering_background(resume_text: str, infrastructure: bool = False) -> bool:
    titles = (r"运维工程师|DevOps|系统工程师|基础设施工程师" if infrastructure else
              r"软件工程师|开发工程师|全栈工程师|后端工程师|前端工程师|软件研发")
    for match in re.finditer(titles, resume_text, re.I):
        before, after = resume_text[max(0, match.start()-12):match.start()], resume_text[match.end():match.end()+8]
        if re.search(r"没有|不具备|并非|不是|缺少|尚无|协同|配合", before) or re.match(r"团队|部门", after):
            continue
        return True
    return False


def _graduation_year(resume_text: str) -> int | None:
    years = []
    patterns = (
        r"(?:毕业时间|毕业于|毕业年份)\s*[:：]?\s*(?P<year>(?:19|20)\d{2})",
        r"(?P<year>(?:19|20)\d{2})\s*年毕业",
        r"(?:博士|硕士|学士|本科|专科)[^\d。；\n]{0,20}(?:19|20)\d{2}[./年]\d{1,2}\s*[-~至—–]\s*(?P<year>(?:19|20)\d{2})",
    )
    for pattern in patterns:
        years.extend(int(m['year']) for m in re.finditer(pattern, resume_text))
    return max(years) if years else None


def role_fit_failures(resume_text: str, job: dict[str, Any], detail: str) -> list[str]:
    """Shared deterministic gates for both search scoring and daily selection."""
    detail = unicodedata.normalize('NFKC', str(detail or ''))
    resume_text = unicodedata.normalize('NFKC', str(resume_text or ''))
    role = role_content(detail)
    required = _mandatory_clauses(detail)
    title = str(job.get('jobName') or job.get('title') or '')
    failures = []
    issue = detail_content_issue(detail)
    if issue and '不足80字' not in issue:
        failures.append(issue)
    graduation = re.search(r"毕业时间\s*[:：]?\s*(20\d{2})|(?:仅限|面向|招聘)?\s*(20\d{2})\s*届", f'{title}\n{role}')
    graduation_flexible = re.search(r'不限毕业|不限制毕业|社招(?:也)?(?:可|均可)|应届.{0,8}或.{0,8}(?:社招|有经验)', role)
    candidate_year = _graduation_year(resume_text)
    if graduation and candidate_year and not graduation_flexible:
        required_year = int(graduation.group(1) or graduation.group(2))
        if required_year != candidate_year:
            failures.append(f'明确限定{required_year}届毕业，候选人已确认毕业年份为{candidate_year}')
    development = (
        r"(?:扎实|熟练|精通).{0,12}软件开发能力|全栈开发|全栈交付(?:的)?能力|开发前后端|生产系统.{0,8}(?:开发|编码)|自己.{0,4}写代码"
        r"|(?:亲自|独立|亲手).{0,10}(?:编写|开发|评审).{0,60}(?:代码|后端|数据管道|数据集成|业务应用)"
        r"|(?:熟练|精通|扎实).{0,12}(?:后端语言|后端开发)"
    )
    research_years = re.search(rf"{_YEAR_TOKEN}\s*年(?:以上|及以上)?(?:软件|技术|后端|前端|全栈)?(?:研发|开发)(?:工作)?经验", required)
    if (re.search(development, required, re.I) or research_years) and not _engineering_background(resume_text):
        failures.append('核心要求独立软件开发或生产代码交付，现有经历没有对应工程研发证据；AI辅助原型不替代该经历')
    if '机器人' in title and re.search(r'量产|硬件可靠性|工程化定型', required) and not re.search(r'(?:机器人|智能硬件).{0,16}(?:研发|产品负责人|量产)', resume_text):
        failures.append('核心为机器人硬件产品线、工程化量产及组织管理，现有材料没有对应专业经历')
    if re.search(r'Isaac|MuJoCo|四元数|正逆运动学', required, re.I) and re.search(r'编写.{0,12}脚本|精通\s*Python', required, re.I) and not _engineering_background(resume_text):
        failures.append('核心为机器人数据工程、三维几何或仿真数据管线，现有材料没有对应工程经历')
    infrastructure = re.search(r"(?:精通|熟练|扎实|熟悉).{0,16}(?:linux|unix)", required, re.I)
    operations = sum(term in role.lower() for term in ('运维', '故障', '巡检', '性能优化', '性能调优', '集群', '系统调试'))
    if infrastructure and operations >= 2 and not _engineering_background(resume_text, infrastructure=True):
        failures.append('核心要求Linux/Unix部署运维与系统排障，现有经历没有对应系统工程证据')
    channel_title = re.search(r"(?:渠道|生态|伙伴).{0,8}(?:合作经理|拓展|商务|渠道总监|合作)", title)
    duties = re.split(r'任职要求|岗位要求|任职资格|职位要求|我们希望你', role, maxsplit=1)[0]
    solution_work = re.search(r"方案(?:设计|共创)|共创.{0,12}方案|需求.{0,8}(?:拆解|分析)|(?:智能体|工作流).{0,12}(?:实施|搭建|设计|配置)|场景验证", duties)
    if channel_title and not solution_work:
        failures.append('核心为渠道拓展、伙伴获客和销售转化，缺少AI方案设计、实施或产品定义职责')
    return failures


def _year_value(value: str) -> int | None:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    values = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return values.get(text)


def _required_years(text: str, subject: str) -> int | None:
    patterns = (
        re.compile(rf"(?P<years>{_YEAR_TOKEN})\s*年(?:以上|及以上)?[^。；;\n]{{0,30}}{subject}[^。；;\n]{{0,30}}(?:经验|经历|背景|从业|项目|咨询|实施|研发)", re.I),
        re.compile(rf"{subject}[^。；;\n]{{0,30}}(?P<years>{_YEAR_TOKEN})\s*年(?:以上|及以上)?[^。；;\n]{{0,20}}(?:经验|经历|背景|从业|项目|咨询|实施|研发)", re.I),
    )
    values = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            value = _year_value(match.group("years"))
            if value:
                values.append(value)
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
            if value:
                values.append(value)
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
    found: list[tuple[str, int | None]] = []
    for label, terms in _DOMAIN_GROUPS.items():
        blob = "|".join(re.escape(term) for term in terms)
        years = _required_years(detail, rf"(?:{blob})")
        explicit = re.search(rf"(?:具备|要求|需要|拥有)[^。；;\n]{{0,35}}(?:{blob})[^。；;\n]{{0,18}}(?:深耕|经验|背景|从业)", detail, re.I)
        if years or explicit:
            found.append((label, years))
    return found


def clean_job_text(value: Any, maximum: int = MAX_JOB_TEXT_LENGTH) -> SafeJobText:
    raw = unicodedata.normalize("NFKC", html.unescape(str(value or "")))
    warnings: list[str] = []
    if _TAG.search(raw):
        raw = _TAG.sub(" ", raw)
        warnings.append("已清理残留HTML")
    if _HIDDEN.search(raw):
        raw = _HIDDEN.sub("", raw)
        warnings.append("已清理隐藏字符")
    raw = "".join(ch for ch in raw if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    if _URL.search(raw):
        warnings.append("JD正文包含链接，系统不会访问")
    if _PROMPT_LIKE.search(raw):
        warnings.append("JD含疑似指令文本，仅按普通文字处理")
    if len(raw) > maximum:
        raw = raw[:maximum]
        warnings.append(f"JD超过{maximum}字，已截断")
    return SafeJobText(raw, list(dict.fromkeys(warnings)))


def _parse_date_text(value: str, as_of: date) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = _DATE_YMD.search(text)
    if match:
        try:
            return date(int(match["y"]), int(match["m"]), int(match["d"]))
        except ValueError:
            return None
    match = _DATE_MD.search(text)
    if match:
        try:
            candidate = date(as_of.year, int(match["m"]), int(match["d"]))
            if candidate < as_of and (as_of - candidate).days > 180:
                candidate = date(as_of.year + 1, candidate.month, candidate.day)
            return candidate
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def extract_deadline(structured: Any, detail: str, as_of: date | None = None) -> str:
    reference = as_of or date.today()
    parsed = _parse_date_text(str(structured or ""), reference)
    if parsed:
        return parsed.isoformat()
    match = _DEADLINE_LINE.search(detail)
    if not match:
        return ""
    parsed = _parse_date_text(match.group(1), reference)
    return parsed.isoformat() if parsed else ""


def posting_status(deadline: str, as_of: date | None = None) -> str:
    if not deadline:
        return "unknown"
    reference = as_of or date.today()
    try:
        value = date.fromisoformat(deadline)
    except ValueError:
        return "unknown"
    days = (value - reference).days
    if days < 0:
        return "expired"
    if days <= 7:
        return "closing_soon"
    return "active"


def evaluate_eligibility(
    resume_text: str,
    job: dict[str, Any],
    detail: str,
    deadline_status: str,
    target_city: str | Iterable[str] = "深圳",
    excluded_keywords: Iterable[str] | None = None,
    strict_matching: bool = True, exclude_staffing_agencies: bool = True,
    *, as_of: date | None = None, max_update_age_days: int = MAX_JOB_UPDATE_AGE_DAYS,
) -> EligibilityResult:
    resume_text = unicodedata.normalize("NFKC", str(resume_text or ""))
    detail = unicodedata.normalize("NFKC", str(detail or ""))
    full_detail = detail
    fit_failures = role_fit_failures(resume_text, job, detail) if strict_matching else []
    detail = role_content(detail)
    mandatory = _mandatory_clauses(detail)
    resume_lower, detail_lower = resume_text.lower(), detail.lower()
    failures: list[str] = fit_failures
    stale_reason = stale_update_reason(job.get('publishedAt') or job.get('publishTime') or job.get('datePosted'), as_of, max_update_age_days)
    if stale_reason:
        failures.append(stale_reason)
    flags: list[str] = []
    outsourcing_reason = detect_outsourcing(job, full_detail, exclude_staffing_agencies=exclude_staffing_agencies)
    if outsourcing_reason:
        failures.append(f"明确外包：{outsourcing_reason}")
    education = str(job.get("education") or job.get("jobDegree") or "")
    if ("博士" in education or re.search(r"博士(?:学历|及以上|以上)", mandatory)) and "博士" not in resume_text:
        failures.append("明确要求博士学历，简历没有相应证据")
    elif ("硕士" in education or re.search(r"硕士(?:学历|及以上|以上)", mandatory)) and not any(x in resume_text for x in ("硕士", "博士")):
        failures.append("明确要求硕士及以上学历，简历没有相应证据")
    mandatory_languages = _mandatory_clauses(detail).lower()
    language_clauses = []
    for clause in mandatory_languages.splitlines():
        choices = [term for term in ('python','java','golang','go','c++','typescript','javascript') if has_term(clause,term)]
        if re.search(r'任一|任意一|至少一|其中一', clause) and any(has_term(resume_lower, term) for term in choices):
            continue
        language_clauses.append(clause)
    mandatory_languages = '\n'.join(language_clauses)
    for language in ("python", "java", "golang", "c++"):
        if re.search(rf"(?:精通|熟练|必须掌握|硬性要求|熟悉).{{0,16}}(?<![a-z]){re.escape(language)}(?![a-z])", mandatory_languages) and not has_term(resume_lower, language):
            failures.append(f"明确要求熟练掌握{language}，简历没有相应证据")
        elif re.search(rf"(?:具备|掌握|要求).{{0,16}}(?<![a-z]){re.escape(language)}(?![a-z])|(?<![a-z]){re.escape(language)}(?![a-z]).{{0,12}}(?:基础|能力|经验)", mandatory_languages) and not has_term(resume_lower, language):
            flags.append(f"岗位要求{language}基础能力，简历没有明确证据")
        elif re.search(rf'(?:精通|熟练掌握|熟练使用)\s*{re.escape(language)}(?![a-z])', mandatory_languages) and not _engineering_background(resume_text):
            flags.append(f'明确要求熟练{language}，现有材料中的工具或AI辅助原型经历不能单独证明该熟练度，需要核对')
    if re.search(r'(?:熟悉|精通).{0,30}(?:SCRM|CDP|营销自动化)', mandatory, re.I) and not re.search(r'SCRM|CDP|营销自动化|营销云', resume_text, re.I):
        flags.append('明确要求零售营销SaaS产品知识与实践，现有材料缺少对应证据，需要核对')
    if strict_matching:
        ai_required = _required_years(mandatory, _AI_TERMS)
        candidate_ai = _candidate_ai_years(resume_text)
        if ai_required:
            if candidate_ai is None:
                flags.append(f"明确要求{ai_required}年以上AI相关经验，简历中的AI年限需要确认")
            elif ai_required > candidate_ai:
                flags.append(f"AI相关经验要求{ai_required}年以上，简历仅有约{candidate_ai}年明确证据；仅作谨慎提示，不单独排除")
        product_required = _required_years(mandatory, _PRODUCT_TERMS)
        if product_required and not re.search(r"产品经理|产品负责人|产品总监|产品甲方", resume_text, re.I):
            flags.append(f"明确要求{product_required}年以上正式产品经验，简历缺少对应职位证据")
        cloud_required = _required_years(mandatory, r'(?:云计算|公有云)')
        cloud_evidence = _required_years(resume_text, r'(?:云计算|公有云)')
        if cloud_required and (cloud_evidence is None or cloud_evidence < cloud_required):
            flags.append(f'明确要求{cloud_required}年以上云计算/公有云方案经验，现有经历缺少对应年限证据，需进一步核对')
        software_required = _required_years(mandatory, _SOFTWARE_TERMS)
        software_evidence = _engineering_background(resume_text)
        if software_required and not software_evidence:
            failures.append(f"明确要求{software_required}年以上软件研发经验，简历没有对应职位证据")
        if re.search(r"全栈(?:工程|开发)能力|独立(?:完成|负责).{0,18}(?:前后端|生产系统|核心代码)", detail, re.I) and not software_evidence:
            failures.append("明确要求全栈或生产级软件工程能力，简历没有对应证据")
        technical_engineering_signals = (
            bool(re.search(r"模型训练|模型微调|训练调参|特征工程|强化学习", detail, re.I)),
            bool(re.search(r"mlops|gpu集群|分布式训练|模型仓库|特征平台", detail, re.I)),
            bool(re.search(r"核心代码|代码审查|AI平台.{0,12}(?:开发|维护)|推理平台.{0,12}(?:开发|维护)", detail, re.I)),
            bool(re.search(r"推理服务|grpc|保障sla|性能压测|吞吐和延迟", detail, re.I)),
        )
        title = str(job.get("jobName") or job.get("title") or "")
        model_engineering_title = bool(re.search(
            r"(?:大模型|AI|机器学习|深度学习).{0,8}(?:算法|训练).{0,8}(?:专家|工程师|研究员)"
            r"|(?:算法|模型训练|机器学习|深度学习)(?:专家|工程师|研究员)",
            title,
            re.I,
        ))
        model_lifecycle_duty = bool(re.search(
            r"(?:设计|调试|训练|微调).{0,12}(?:大模型|模型|LLM|MLLM)"
            r"|(?:大模型|模型|LLM|MLLM).{0,12}(?:训练|微调|调试)"
            r"|fine[- ]?tune|数据.{0,12}(?:送标|标注).{0,12}(?:训练|微调|评估)",
            detail,
            re.I,
        ))
        model_framework_duty = bool(re.search(r"pytorch|tensorflow|深度学习框架|数据\s*pipeline", detail, re.I))
        pure_model_engineering = model_engineering_title and model_lifecycle_duty and model_framework_duty
        if (sum(technical_engineering_signals) >= 2 or pure_model_engineering) and not software_evidence:
            failures.append("岗位核心为AI平台、模型训练或推理工程，简历没有生产研发背景")
        for domain_label, required_years in _domain_requirements(mandatory):
            terms = _DOMAIN_GROUPS[domain_label]
            if any(term.lower() in resume_lower for term in terms):
                continue
            if required_years and required_years >= 3:
                failures.append(f"明确要求{required_years}年以上{domain_label}经验，简历没有对应行业证据")
            else:
                flags.append(f"岗位要求{domain_label}深耕经验，简历证据需要确认")
    embedded_terms = ("mcu", "rtos", "freertos", "rt-thread", "cortex-m", "bootloader", "驱动开发")
    if any(term in mandatory.lower() for term in embedded_terms) and not any(term in resume_lower for term in embedded_terms):
        failures.append("明确要求嵌入式系统开发能力，简历没有相应证据")
    for keyword in excluded_keywords or []:
        if str(keyword).strip() and str(keyword).lower() in f"{job.get('jobName', '')} {full_detail}".lower():
            failures.append(f"命中不考虑关键词：{str(keyword).strip()}")
    location = str(job.get("location") or job.get("city") or "")
    target_cities = [target_city] if isinstance(target_city, str) else list(target_city)
    if location and target_cities and not location_matches_city(location, target_cities) and re.search(r"现场办公|必须到岗|工作地点", detail) and not re.search(r"远程|可居家", detail):
        failures.append(f"明确现场工作地点为{location}，不在目标城市{'、'.join(str(city) for city in target_cities)}")
    if deadline_status == "expired":
        failures.append("招聘截止日期已经过去")
    if re.search(r"(?:英语|英文).{0,15}(?:流利|熟练|商务|六级|cet-?6|必需|必须)", detail_lower) and not any(x in resume_lower for x in ("英语", "english", "cet", "toefl", "ielts")):
        flags.append("英语能力要求需要人工确认")
    travel = re.sub(r'(?:不需(?:要)?|无需|不要求|不安排)(?:长期|高频|频繁)?出差', '', mandatory)
    if re.search(r"高频出差|频繁出差|长期出差|出差.{0,5}(?:50%|一半)", travel):
        flags.append("岗位包含高频出差，需要人工确认")
    if re.search(r"长期驻场|常驻客户|驻场交付", detail):
        flags.append("岗位包含长期或客户驻场，需要人工确认")
    if failures:
        return EligibilityResult("fail", list(dict.fromkeys(failures + flags)))
    if flags:
        return EligibilityResult("flag", list(dict.fromkeys(flags)))
    return EligibilityResult("pass", [])
