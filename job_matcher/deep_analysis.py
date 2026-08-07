from __future__ import annotations

import re
from typing import Any, Iterable

DEEP_ANALYSIS_THRESHOLD = 75

def validate_deep_analysis(raw: Any, allowed_facts: Iterable[str], forbidden_claims: Iterable[str]) -> dict[str, Any]:
    if not isinstance(raw, dict): raise ValueError("深度分析必须是JSON对象")
    if any(key in raw for key in ("priority", "deciding_factor", "questions", "interview_evidence")):
        priority = _string(raw.get("priority"), 8, 120, "投递优先级")
        deciding_factor = _string(raw.get("deciding_factor"), 8, 160, "决定成败的关键点")
        questions = _string_list(raw.get("questions"), 1, 2, "待确认问题")
        interview_evidence = _string_list(raw.get("interview_evidence"), 1, 2, "面试举证")
        combined = " ".join([priority, deciding_factor] + questions + interview_evidence)
        if re.search(r"https?://", combined, re.I): raise ValueError("投递策略不得包含或访问JD正文链接")
        if any(term.lower() in combined.lower() for term in forbidden_claims): raise ValueError("投递策略包含未经确认的能力描述")
        facts = [str(item).strip() for item in allowed_facts if str(item).strip()]
        if facts and not any(fact.lower() in " ".join(interview_evidence).lower() for fact in facts): raise ValueError("面试举证没有引用候选人已确认信息")
        return {"format": "strategy_v1", "priority": priority, "deciding_factor": deciding_factor, "questions": questions, "interview_evidence": interview_evidence}
    strengths = _string_list(raw.get("strengths"), 3, 3, "核心匹配点")
    risks = _string_list(raw.get("risks"), 1, 2, "主要风险")
    evidence = _string_list(raw.get("evidence"), 2, 4, "履历事实")
    recommendation = str(raw.get("recommendation") or "").strip()
    if not 15 <= len(recommendation) <= 160: raise ValueError("投递建议必须为15—160字")
    combined = " ".join(strengths + risks + evidence + [recommendation])
    if re.search(r"https?://", combined, re.I): raise ValueError("深度分析不得包含或访问JD正文链接")
    if any(term.lower() in combined.lower() for term in forbidden_claims): raise ValueError("深度分析包含未经确认的能力描述")
    facts = [str(item).strip() for item in allowed_facts if str(item).strip()]
    if facts and not any(fact.lower() in " ".join(evidence).lower() for fact in facts): raise ValueError("履历事实没有引用候选人已确认信息")
    return {"format": "legacy", "strengths": strengths, "risks": risks, "evidence": evidence, "recommendation": recommendation}

def apply_deep_analyses(jobs: list[Any], analyses: dict[str, Any] | None, allowed_facts: Iterable[str], forbidden_claims: Iterable[str]) -> list[str]:
    provided = analyses if isinstance(analyses, dict) else {}; errors: list[str] = []
    eligible_ids = {str(job.job_id) for job in jobs if int(job.score) >= DEEP_ANALYSIS_THRESHOLD and getattr(job, "eligibility_verdict", "pass") != "fail" and not getattr(job, "is_excluded", False)}
    for unknown in set(provided) - eligible_ids: errors.append(f"忽略未知或不符合门槛的岗位：{unknown}")
    for job in jobs:
        job.deep_analysis = None; job.deep_analysis_error = ""
        if str(job.job_id) not in eligible_ids: continue
        raw = provided.get(str(job.job_id))
        if raw is None: job.deep_analysis_error = "投递策略未完成"; errors.append(f"{job.job_id} 投递策略缺失"); continue
        try: job.deep_analysis = validate_deep_analysis(raw, allowed_facts, forbidden_claims)
        except ValueError as exc: job.deep_analysis_error = f"投递策略未完成：{exc}"; errors.append(f"{job.job_id} {exc}")
    return errors

def require_complete_deep_analyses(jobs: list[Any]) -> None:
    missing = [str(job.job_id) for job in jobs if int(job.score) >= DEEP_ANALYSIS_THRESHOLD and getattr(job, "eligibility_verdict", "pass") != "fail" and not getattr(job, "is_excluded", False) and not getattr(job, "deep_analysis", None)]
    if missing: raise ValueError("以下75分以上岗位的投递策略未完成：" + "、".join(missing))

def _string(value: Any, minimum: int, maximum: int, label: str) -> str:
    result = str(value or "").strip()
    if not minimum <= len(result) <= maximum: raise ValueError(f"{label}必须为{minimum}—{maximum}字")
    return result

def _string_list(value: Any, minimum: int, maximum: int, label: str) -> list[str]:
    if not isinstance(value, list): raise ValueError(f"{label}必须是数组")
    items = [str(item).strip() for item in value if str(item).strip()]
    if not minimum <= len(items) <= maximum: raise ValueError(f"{label}必须包含{minimum}—{maximum}项")
    if any(len(item) > 120 for item in items): raise ValueError(f"{label}单项不能超过120字")
    return items
