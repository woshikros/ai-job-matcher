from __future__ import annotations

import shutil
from datetime import date as current_date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .candidate_profile import ROLE_OPTIONS, extract_profile_suggestions, get_candidate_profile, profile_is_complete, save_candidate_profile
from .cli_client import LiepinCliError, search_jobs
from .backup import export_backup, parse_backup, restore_backup
from .resume import ResumeReadError, extract_resume_text
from .scoring import job_text, score_job
from .salary import DEFAULT_SALARY_UPPER_FLOOR, SALARY_OPTIONS, normalise_salary_floor
from .skill_gaps import generate_skill_gap_report
from .storage import (
    DATA_DIR, get_application_statistics, get_report_summary, get_setting, get_source_health, initialize, list_report_dates, list_skill_gap_report_dates, load_daily_report, load_skill_gap_report,
    save_search, save_setting, set_job_status,
)

app = FastAPI(title="双平台AI岗位面板")
LOCAL_ORIGINS = {"http://127.0.0.1:8000", "http://localhost:8000"}
app.add_middleware(CORSMiddleware, allow_origins=sorted(LOCAL_ORIGINS), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
templates = Jinja2Templates(directory="templates")
UPLOADS = Path("uploads")


@app.on_event("startup")
def startup() -> None:
    initialize()
    UPLOADS.mkdir(exist_ok=True)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, date: str | None = None, status: str = "all", source: str = "all", freshness: str = "all"):
    profile = get_candidate_profile()
    profile_complete = profile_is_complete(profile)
    report_date, jobs = load_daily_report(date)
    if status in {"pending", "applied", "dismissed"}:
        jobs = [item for item in jobs if item.get("status") == status]
    if source in {"liepin", "zhilian"}:
        jobs = [item for item in jobs if item.get("source", "liepin") == source]
    jobs = _filter_freshness(jobs, freshness)
    report_dates = list_report_dates()
    summary = get_report_summary(report_date)
    source_health = list(summary.get("source_health", []))
    if report_date == current_date.today().isoformat():
        current_zhilian = {**get_source_health("zhilian"), "label": "智联招聘"}
        source_health = [item for item in source_health if item.get("source") != "zhilian"]
        if not any(item.get("source") == "liepin" for item in source_health):
            source_health.insert(0, {"source": "liepin", "status": "ok", "enabled": True, "label": "猎聘"})
        source_health.append(current_zhilian)
    return templates.TemplateResponse(
        request,
        "daily_report.html",
        {
            "address": "、".join(profile.get("cities", [])), "generated_at": "", "report_date": report_date,
            "jobs": jobs, "qualified": sum(int(item.get("score", 0)) >= 70 and not item.get("is_excluded") for item in jobs),
            "supplemental": sum(bool(item.get("is_supplemental")) and not item.get("is_excluded") for item in jobs),
            "excluded_count": sum(bool(item.get("is_excluded")) for item in jobs),
            "report_dates": report_dates, "status_filter": status,
            "source_filter": source, "freshness_filter": freshness, "source_health": source_health,
            "application_stats": get_application_statistics(),
            "source_labels": {"liepin": "猎聘", "zhilian": "智联招聘"},
            "latest_skill_gap_report": load_skill_gap_report(),
            "candidate_profile": profile, "profile_complete": profile_complete,
            "resume_name": get_setting("resume_name", "未上传"),
        },
    )


@app.post("/api/reports/skill-gaps")
def create_skill_gap_report():
    try:
        generate_skill_gap_report()
    except ValueError as exc:
        return RedirectResponse(f"/?error={exc}", status_code=303)
    return RedirectResponse("/skill-gaps", status_code=303)


@app.get("/skill-gaps", response_class=HTMLResponse)
def skill_gap_report(request: Request, date: str | None = None):
    report = load_skill_gap_report(date)
    if not report:
        return RedirectResponse("/?error=还没有能力差距报告", status_code=303)
    return templates.TemplateResponse(request, "skill_gap_report.html", {"report": report, "report_dates": list_skill_gap_report_dates()})


@app.get("/settings", response_class=HTMLResponse)
def index(request: Request, message: str = "", error: str = ""):
    return templates.TemplateResponse(request, "index.html", {
        "preferences": get_setting("preferences", {}), "profile": get_candidate_profile(), "role_options": ROLE_OPTIONS,
        "custom_roles": [item for item in get_candidate_profile().get("target_roles", []) if item not in ROLE_OPTIONS],
        "resume_name": get_setting("resume_name", "未上传"), "results": get_setting("last_results", []),
        "message": message, "error": error, "salary_options": SALARY_OPTIONS,
    })


@app.post("/profile")
def update_candidate_profile(cities: Annotated[str, Form()] = "", target_roles: Annotated[list[str] | None, Form()] = None, custom_roles: Annotated[str, Form()] = "", salary_upper_floor: Annotated[int, Form()] = DEFAULT_SALARY_UPPER_FLOOR, excluded_keywords: Annotated[str, Form()] = "", confirmed_skills: Annotated[str, Form()] = "", confirmed_achievements: Annotated[str, Form()] = ""):
    roles = list(target_roles or [])
    if custom_roles.strip(): roles.extend(custom_roles.replace("，", "\n").replace(",", "\n").splitlines())
    profile = save_candidate_profile({"cities": cities, "target_roles": roles, "salary_upper_floor": salary_upper_floor, "excluded_keywords": excluded_keywords, "confirmed_skills": confirmed_skills, "confirmed_achievements": confirmed_achievements})
    if not profile.get("cities") or not profile.get("target_roles"): return RedirectResponse("/settings?error=请至少填写一个城市并选择一个目标岗位方向", status_code=303)
    return RedirectResponse("/settings?message=求职档案已保存，今后的工作日报会使用这些设置", status_code=303)


class StatusUpdate(BaseModel):
    status: str
    fingerprint: str
    source: str | None = None


@app.post("/api/jobs/{job_id}/status")
def update_job_status(job_id: str, payload: StatusUpdate):
    if payload.status not in {"pending", "applied", "dismissed"}:
        return JSONResponse({"error": "无效状态"}, status_code=400)
    set_job_status(job_id, payload.fingerprint, payload.status, payload.source)
    return {"ok": True, "job_id": job_id, "status": payload.status, "statistics": get_application_statistics()}


@app.get("/api/statistics/applications")
def application_statistics():
    return get_application_statistics()


@app.get("/api/backup")
def download_backup():
    filename = f"ai-job-matcher-backup-{current_date.today().isoformat()}.json"
    return JSONResponse(export_backup(), headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/backup/restore")
def upload_backup(request: Request, file: Annotated[UploadFile, File()]):
    origin = request.headers.get("origin")
    if origin and origin not in LOCAL_ORIGINS:
        return JSONResponse({"error": "只允许从本机岗位面板恢复备份"}, status_code=403)
    try: restored = restore_backup(parse_backup(file.file.read()))
    except ValueError as exc: return RedirectResponse(f"/?error={exc}", status_code=303)
    return RedirectResponse(f"/?message=备份已恢复，共写入{sum(restored.values())}条记录", status_code=303)


@app.post("/resume")
def upload_resume(file: Annotated[UploadFile, File()]):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt"):
        return RedirectResponse("/?error=仅支持 PDF、DOCX 或 TXT 简历", status_code=303)
    target = UPLOADS / f"resume{suffix}"
    with target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    try:
        text = extract_resume_text(target)
    except ResumeReadError as exc:
        target.unlink(missing_ok=True)
        return RedirectResponse(f"/?error={exc}", status_code=303)
    save_setting("resume_text", text)
    save_setting("resume_name", file.filename)
    profile = get_candidate_profile(); skills, achievements = extract_profile_suggestions(text)
    if not profile.get("confirmed_skills"): profile["confirmed_skills"] = skills
    if not profile.get("confirmed_achievements"): profile["confirmed_achievements"] = achievements
    save_candidate_profile(profile)
    return RedirectResponse("/settings?message=简历已读取并仅保存在本机，请核对自动提取的技能和成果", status_code=303)


@app.post("/preferences")
def save_preferences(job_name: Annotated[str, Form()], address: Annotated[str, Form()] = "", salary_floor: Annotated[str, Form()] = "", page: Annotated[int, Form()] = 0):
    save_setting("preferences", {"job_name": job_name, "address": address, "salary_floor": salary_floor, "page": page})
    current = get_candidate_profile(); current.update({"target_roles": [job_name], "cities": [address] if address else current.get("cities", []), "salary_upper_floor": _normalise_salary(salary_floor) or DEFAULT_SALARY_UPPER_FLOOR}); save_candidate_profile(current)
    return RedirectResponse("/settings?message=默认条件已保存", status_code=303)


@app.post("/search")
def run_search(job_name: Annotated[str, Form()] = "", address: Annotated[str, Form()] = "", salary_floor: Annotated[str, Form()] = "", page: Annotated[int, Form()] = 0):
    resume_text = get_setting("resume_text")
    if not resume_text:
        return RedirectResponse("/?error=请先上传简历", status_code=303)
    defaults = get_setting("preferences", {})
    salary = salary_floor or defaults.get("salary_floor")
    try:
        normalised_salary = _normalise_salary(salary)
    except ValueError:
        return RedirectResponse("/?error=最低月薪请填写数字，例如 35000 或 35k", status_code=303)
    filters = {"jobName": job_name or defaults.get("job_name"), "address": address or defaults.get("address"), "salaryFloor": normalised_salary, "page": page}
    try:
        jobs = search_jobs(filters)
    except LiepinCliError as exc:
        return RedirectResponse(f"/?error={exc}", status_code=303)
    results = []
    for job in jobs:
        match = score_job(resume_text, job, str(filters.get("jobName") or ""), [str(filters.get("address") or "")], normalised_salary or 0)
        results.append({"score": match.score, "matched": match.matched_skills, "missing": match.missing_skills, "reason": match.reason, "ai_note": match.ai_note, "breakdown": match.breakdown, "evidence": match.evidence, "hard_knockouts": match.hard_knockouts, "summary": job_text(job)[:600], "raw": job})
    results.sort(key=lambda item: item["score"], reverse=True)
    save_setting("last_results", results)
    save_search(filters, results)
    return RedirectResponse(f"/?message=已查询并分析 {len(results)} 个职位", status_code=303)


def _normalise_salary(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower().replace(",", "")
    if text.endswith("k"):
        return int(float(text[:-1]) * 1000)
    return int(float(text))


def _filter_freshness(jobs: list[dict], freshness: str) -> list[dict]:
    if freshness == "new": return [item for item in jobs if item.get("is_new")]
    if freshness == "3d":
        today = current_date.today(); filtered = []
        for item in jobs:
            try:
                if (today - current_date.fromisoformat(str(item.get("first_seen", ""))[:10])).days <= 2: filtered.append(item)
            except ValueError: filtered.append(item)
        return filtered
    return jobs
