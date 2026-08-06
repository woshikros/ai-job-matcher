from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from .salary import DEFAULT_SALARY_UPPER_FLOOR, normalise_salary_floor
from .storage import get_setting, save_setting


ROLE_OPTIONS = (
    "AI解决方案架构师",
    "Solution FDE/业务型FDE",
    "AI产品负责人/AI产品经理",
    "AI转型顾问",
    "Agent解决方案",
)

ROLE_QUERY_MAP = {
    "AI解决方案架构师": ("AI解决方案架构师", "AI应用架构师", "AI解决方案工程师"),
    "Solution FDE/业务型FDE": ("FDE", "Forward Deployed Engineer", "前沿部署工程师"),
    "AI产品负责人/AI产品经理": ("AI产品负责人", "AI产品经理", "Agent产品"),
    "AI转型顾问": ("AI转型顾问", "AI Transformation"),
    "Agent解决方案": ("Agent解决方案", "智能体解决方案", "AI Agent"),
}

DEFAULT_PROFILE: dict[str, Any] = {
    "cities": [],
    "target_roles": [],
    "salary_upper_floor": DEFAULT_SALARY_UPPER_FLOOR,
    "excluded_keywords": [],
    "confirmed_skills": [],
    "confirmed_achievements": [],
}


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.replace("；", "\n").replace("，", "\n").replace(",", "\n").splitlines()
    if not isinstance(value, Iterable) or isinstance(value, (bytes, dict)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def get_candidate_profile() -> dict[str, Any]:
    try:
        stored = get_setting("candidate_profile", {})
        legacy = get_setting("preferences", {})
        saved_floor = get_setting("salary_upper_floor", DEFAULT_SALARY_UPPER_FLOOR)
    except sqlite3.OperationalError:
        stored, legacy, saved_floor = {}, {}, DEFAULT_SALARY_UPPER_FLOOR
    result = {**DEFAULT_PROFILE, **(stored if isinstance(stored, dict) else {})}
    if not stored and isinstance(legacy, dict):
        if legacy.get("address") and not result.get("cities"):
            result["cities"] = _list(legacy["address"])
        if legacy.get("job_name") and not result.get("target_roles"):
            result["target_roles"] = _list(legacy["job_name"])
    for key in ("cities", "target_roles", "excluded_keywords", "confirmed_skills", "confirmed_achievements"):
        result[key] = _list(result.get(key, []))
    result["salary_upper_floor"] = normalise_salary_floor(
        result.get("salary_upper_floor", saved_floor)
    )
    return result


def save_candidate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    cleaned = {
        "cities": _list(profile.get("cities")),
        "target_roles": _list(profile.get("target_roles")),
        "salary_upper_floor": normalise_salary_floor(profile.get("salary_upper_floor", DEFAULT_SALARY_UPPER_FLOOR)),
        "excluded_keywords": _list(profile.get("excluded_keywords")),
        "confirmed_skills": _list(profile.get("confirmed_skills")),
        "confirmed_achievements": _list(profile.get("confirmed_achievements")),
    }
    save_setting("candidate_profile", cleaned)
    save_setting("salary_upper_floor", cleaned["salary_upper_floor"])
    return cleaned


def profile_is_complete(profile: dict[str, Any] | None = None) -> bool:
    profile = profile or get_candidate_profile()
    try:
        resume_text = get_setting("resume_text")
    except sqlite3.OperationalError:
        resume_text = ""
    return bool(resume_text and profile.get("cities") and profile.get("target_roles"))


def profile_queries(profile: dict[str, Any] | None = None) -> list[str]:
    profile = profile or get_candidate_profile()
    queries: list[str] = []
    for role in profile.get("target_roles", []):
        queries.extend(ROLE_QUERY_MAP.get(role, (role,)))
    return list(dict.fromkeys(item for item in queries if item))


def profile_facts(profile: dict[str, Any] | None = None) -> tuple[str, ...]:
    profile = profile or get_candidate_profile()
    return tuple(profile.get("confirmed_skills", []) + profile.get("confirmed_achievements", []))


def extract_profile_suggestions(resume_text: str) -> tuple[list[str], list[str]]:
    skill_terms = ("AI Agent", "Agent", "Workflow", "Skill", "MCP", "API", "Codex", "Claude Code", "RAG", "Prompt", "SQL", "Python", "Java", "Docker", "Kubernetes")
    lowered = resume_text.lower(); skills = [term for term in skill_terms if term.lower() in lowered]; achievements: list[str] = []
    for raw in resume_text.replace("。", "\n").replace("；", "\n").splitlines():
        line = " ".join(raw.strip(" -•\t").split())
        if 8 <= len(line) <= 90 and any(term in line for term in ("搭建", "开发", "落地", "交付", "完成", "负责", "主导", "中标", "上线")): achievements.append(line)
    return list(dict.fromkeys(skills))[:15], list(dict.fromkeys(achievements))[:8]
