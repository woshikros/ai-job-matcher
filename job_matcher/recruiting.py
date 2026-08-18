from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

RECRUITER_TYPES = {"employer", "headhunter", "unknown"}

@dataclass(frozen=True)
class RecruiterIdentity:
    recruiter_type: str
    name: str = ""
    title: str = ""
    evidence: str = ""

_OUTSOURCING_PATTERNS = (
    (re.compile(r"(?:外包岗|外包岗位|岗位外包|职位外包|人员外包|人力外包|用工外包|外包编制|驻场外包|外派外包)"), "岗位明确属于外包用工"),
    (re.compile(r"(?:劳务派遣|人才派遣|人力派遣|派遣制用工|劳务外派)"), "岗位明确采用劳务派遣"),
    (re.compile(r"(?:第三方|人力资源公司).{0,18}(?:签订|签署|劳动合同|发薪|代发薪|缴纳社保|用工)"), "岗位明确由第三方签约或发薪"),
    (re.compile(r"(?:供应商编制|供应商用工|项目制外包用工|非甲方编制)"), "岗位明确属于供应商或外包编制"),
)

def detect_outsourcing(job: dict[str, Any], detail: str, *, exclude_staffing_agencies: bool = True) -> str:
    company = str(job.get("company") or "")
    if exclude_staffing_agencies and re.search(r"人力资源服务|劳务派遣|人才派遣|人力外包", company):
        return "岗位发布主体为人力资源或劳务服务机构"
    text = " ".join((str(job.get("jobName") or ""), company, str(detail or "")))
    for pattern, reason in _OUTSOURCING_PATTERNS:
        if pattern.search(text): return reason
    return ""

def classify_recruiter(job: dict[str, Any], detail: str) -> RecruiterIdentity:
    source = str(job.get("source") or "liepin"); company = str(job.get("company") or job.get("brandName") or "").strip()
    name = str(job.get("recruiterName") or job.get("bossName") or job.get("hrName") or "").strip()
    title = str(job.get("recruiterTitle") or job.get("bossTitle") or "").strip(); detail_text = str(detail or "")
    if "某" in company: return RecruiterIdentity("headhunter", name, title, "公司名称为匿名客户名称")
    if re.search(r"猎头顾问|寻访顾问|猎头招聘|猎头职位", title): return RecruiterIdentity("headhunter", name, title, f"发布者职位为{title}")
    if re.search(r"猎头代招|受客户委托招聘|受客户委托寻访|代客户招聘", detail_text): return RecruiterIdentity("headhunter", name, title, "JD明确说明由猎头代招")
    if source == "zhipin" and (name or title) and re.search(r"hrbp|hr|人事|招聘|总经理|创始人|负责人|招聘者", title, re.I): return RecruiterIdentity("employer", name, title, f"平台发布者职位为{title or '企业招聘者'}")
    return RecruiterIdentity("unknown", name, title, "平台未提供足够的发布者身份信息")

def role_family(title: str) -> str:
    text = str(title or "").lower()
    if "fde" in text or "前线部署" in text or "前沿部署" in text or "交付" in text: return "FDE/交付"
    if "产品" in text: return "AI产品"
    if "咨询" in text or "转型" in text: return "AI转型/咨询"
    if "解决方案" in text or "架构" in text or "售前" in text: return "解决方案/架构"
    return "其他AI岗位"
