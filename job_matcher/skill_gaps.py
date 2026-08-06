from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any, Iterable

from .storage import load_recent_skill_observations, save_skill_gap_report

_NON_SKILL_PREFIXES = ("明确要求", "招聘截止", "英语能力", "岗位包含", "现场工作")

def build_skill_observations(jobs: Iterable[Any], resume_text: str, confirmed_facts: Iterable[str]) -> list[dict[str, Any]]:
    facts = [str(value).strip().lower() for value in confirmed_facts if str(value).strip()]; rows = []
    for job in jobs:
        matched = {str(value).strip() for value in getattr(job, "matched", []) if str(value).strip()}; gaps = {str(value).strip() for value in getattr(job, "gaps", []) if str(value).strip()}
        for skill in sorted(matched | gaps):
            if skill.startswith(_NON_SKILL_PREFIXES): continue
            state = "confirmed" if skill in matched else "weak" if _supported_by_facts(skill, facts) and skill.lower() not in resume_text.lower() else "missing"
            rows.append({"source": str(getattr(job, "source", "")), "job_id": str(getattr(job, "job_id", "")), "fingerprint": str(getattr(job, "fingerprint", "")), "skill": skill, "evidence_state": state, "score": int(getattr(job, "score", 0)), "title": str(getattr(job, "name", "")), "company": str(getattr(job, "company", ""))})
    return rows

def generate_skill_gap_report(report_count: int = 5, report_date: str | None = None) -> dict[str, Any]:
    source_dates, raw_rows = load_recent_skill_observations(report_count)
    if len(source_dates) < 2: raise ValueError("至少需要2个工作日报，才能生成有参考价值的能力差距报告")
    unique = {}
    for row in raw_rows:
        key = (str(row["source"]), str(row["job_id"]), str(row["fingerprint"]), str(row["skill"]))
        if key not in unique or str(row["report_date"]) > str(unique[key]["report_date"]): unique[key] = row
    grouped = defaultdict(list)
    for row in unique.values(): grouped[str(row["skill"])].append(row)
    items, priority = [], {"confirmed": 2, "weak": 1, "missing": 0}
    for skill, rows in grouped.items():
        state = max([str(row["evidence_state"]) for row in rows], key=lambda value: priority.get(value, -1)); examples = []
        for row in sorted(rows, key=lambda value: int(value["score"]), reverse=True):
            label = f"{row['company']} · {row['title']}".strip(" ·")
            if label and label not in examples: examples.append(label)
        items.append({"skill": skill, "state": state, "job_count": len(rows), "average_score": round(sum(int(row["score"]) for row in rows) / len(rows)), "examples": examples[:3], "advice": _advice(state)})
    items.sort(key=lambda item: (item["job_count"], item["state"] != "confirmed", item["average_score"]), reverse=True)
    payload = {"report_count": len(source_dates), "job_count": len({(row["source"], row["job_id"], row["fingerprint"]) for row in unique.values()}), "items": items, "strengths": [x for x in items if x["state"] == "confirmed"][:10], "weak": [x for x in items if x["state"] == "weak"][:10], "missing": [x for x in items if x["state"] == "missing"][:10]}
    target_date = report_date or date.today().isoformat(); save_skill_gap_report(target_date, source_dates, payload)
    return {"report_date": target_date, "source_dates": source_dates, **payload}

def _supported_by_facts(skill: str, facts: list[str]) -> bool:
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", skill.lower())
    return any(value in re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", fact) or re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", fact) in value for fact in facts if value)

def _advice(state: str) -> str:
    return "保留现有证据，并在高相关岗位中优先呈现。" if state == "confirmed" else "补充具体项目、职责和结果，让招聘方能直接看到证据。" if state == "weak" else "先判断是否属于目标岗位的核心要求，再决定学习或降低该类岗位优先级。"
