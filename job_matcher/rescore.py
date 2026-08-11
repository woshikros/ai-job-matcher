from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from .candidate_profile import get_candidate_profile, profile_facts
from .daily_report import _score, mark_cross_platform_duplicates, select_jobs
from .skill_gaps import build_skill_observations
from .storage import get_report_summary, get_setting, load_daily_report, save_daily_report, save_skill_observations


def rescore_saved_report(report_date: str | None = None) -> dict[str, Any]:
    selected_date, old_jobs = load_daily_report(report_date)
    if not selected_date or not old_jobs: raise ValueError("没有可重新评分的日报")
    resume_text = str(get_setting("resume_text", "")); profile = get_candidate_profile()
    if not resume_text or not profile.get("cities") or not profile.get("target_roles"): raise ValueError("请先完成求职档案")
    scored = []
    for old in old_jobs:
        raw = {"jobId": str(old.get("job_id") or ""), "sourceJobId": str(old.get("source_job_id") or ""), "source": str(old.get("source") or "liepin"), "jobName": str(old.get("name") or ""), "company": str(old.get("company") or ""), "location": str(old.get("location") or ""), "salary": str(old.get("salary") or ""), "education": str(old.get("education") or ""), "workYears": str(old.get("work_years") or ""), "industry": str(old.get("industry") or ""), "jobDetailUrl": str(old.get("url") or ""), "deadline": str(old.get("deadline") or ""), "publishedAt": str(old.get("published_at") or "")}
        current = _score(raw, str(old.get("detail") or ""), resume_text, date.fromisoformat(selected_date), profile)
        current.duplicate_group = old.get("duplicate_group"); current.duplicate_sources = list(old.get("duplicate_sources") or [])
        current.greeting = old.get("greeting") if current.score >= 70 and not current.is_excluded else None
        current.deep_analysis = None; current.deep_analysis_error = ""
        scored.append(current)
    jobs = select_jobs(mark_cross_platform_duplicates(scored)); payload = [asdict(item) for item in jobs]; summary = get_report_summary(selected_date)
    save_daily_report(selected_date, "", payload, list(summary.get("source_health", [])))
    save_skill_observations(selected_date, build_skill_observations(jobs, resume_text, profile_facts(profile)))
    return {"report_date": selected_date, "count": len(jobs), "qualified": sum(item.score >= 70 and not item.is_excluded for item in jobs), "excluded": sum(item.is_excluded for item in jobs), "score_version": "v2"}
