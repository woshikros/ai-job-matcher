from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .candidate_profile import get_candidate_profile, profile_facts
from .daily_report import _score, is_priority_job, mark_cross_platform_duplicates, select_jobs, load_prepared_jobs, write_prepared_report, render_report, apply_saved_review
from .skill_gaps import build_skill_observations
from .storage import get_report_summary, get_setting, load_daily_report, save_daily_report, save_skill_observations


def rescore_saved_report(report_date: str | None = None, prepare_output: Path | None = None) -> dict[str, Any]:
    selected_date, old_jobs = load_daily_report(report_date)
    if not selected_date or not old_jobs: raise ValueError("没有可重新评分的日报")
    pool_path=Path('reports')/f'{selected_date}.candidates.json'
    if pool_path.exists():
        previous={item['job_id']:item for item in old_jobs}
        previous.update({item.job_id:asdict(item) for item in load_prepared_jobs(pool_path)})
        old_jobs=list(previous.values())
    resume_text = str(get_setting("resume_text", "")); profile = get_candidate_profile()
    if not resume_text or not profile.get("cities") or not profile.get("target_roles"): raise ValueError("请先完成求职档案")
    scored = []
    for old in old_jobs:
        raw = {"jobId": str(old.get("job_id") or ""), "sourceJobId": str(old.get("source_job_id") or ""), "source": str(old.get("source") or "liepin"), "jobName": str(old.get("name") or ""), "company": str(old.get("company") or ""), "location": str(old.get("location") or ""), "salary": str(old.get("salary") or ""), "education": str(old.get("education") or ""), "workYears": str(old.get("work_years") or ""), "industry": str(old.get("industry") or ""), "jobDetailUrl": str(old.get("url") or ""), "deadline": str(old.get("deadline") or ""), "publishedAt": str(old.get("published_at") or "")}
        current = _score(raw, str(old.get("detail") or ""), resume_text, date.fromisoformat(selected_date), profile)
        current.duplicate_group = old.get("duplicate_group"); current.duplicate_sources = list(old.get("duplicate_sources") or [])
        current.greeting = old.get("greeting") if is_priority_job(current) else None
        current.status=str(old.get('status') or 'pending')
        current.recruiter_type=str(old.get('recruiter_type') or current.recruiter_type)
        current.recruiter_name=str(old.get('recruiter_name') or '')
        apply_saved_review(current,old)
        current.deep_analysis = None; current.deep_analysis_error = ""
        scored.append(current)
    pool=mark_cross_platform_duplicates(scored)
    jobs=select_jobs(pool,evaluation_date=date.fromisoformat(selected_date))
    summary=get_report_summary(selected_date)
    if prepare_output:
        write_prepared_report(pool,prepare_output)
    else:
        path=Path('reports')/f'{selected_date}.html'
        render_report(jobs,{j.job_id:j.greeting for j in jobs if j.greeting},path,selected_date,require_greetings=False,source_health_override=list(summary.get('source_health',[])))
    save_skill_observations(selected_date, build_skill_observations(jobs, resume_text, profile_facts(profile)))
    return {"report_date": selected_date, "count": len(jobs), "qualified": sum(is_priority_job(item) for item in jobs), "excluded": sum(item.is_excluded for item in jobs), "score_version": "v3"}
