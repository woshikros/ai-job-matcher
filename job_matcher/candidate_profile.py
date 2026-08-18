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
    "AI解决方案架构师": ("AI解决方案架构师", "AI应用架构师", "AI解决方案工程师", "AI项目咨询顾问", "企业AI落地顾问"),
    "Solution FDE/业务型FDE": ("FDE", "FDE Consultant", "AI交付工程师", "AI应用顾问", "AI实施顾问", "AI使能顾问"),
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
    "strict_matching": True,
    "exclude_staffing_agencies": True,
    "priority_threshold": 82,
    "consider_threshold": 75,
    "minimum_priority_jobs": 15,
    "cautious_fallback_count": 5,
    "max_headhunter_share": 20,
    "headhunter_free_top_n": 3,
}


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.replace("；", "\n").replace("，", "\n").replace(",", "\n").splitlines()
    if not isinstance(value, Iterable) or isinstance(value, (bytes, dict)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
    result["strict_matching"] = _bool(result.get("strict_matching"), True)
    result["exclude_staffing_agencies"] = _bool(result.get("exclude_staffing_agencies"), True)
    result["priority_threshold"] = _int(result.get("priority_threshold"), 82, 70, 95)
    result["consider_threshold"] = min(
        result["priority_threshold"], _int(result.get("consider_threshold"), 75, 50, 94)
    )
    result["minimum_priority_jobs"] = _int(result.get("minimum_priority_jobs"), 15, 0, 30)
    result["cautious_fallback_count"] = _int(result.get("cautious_fallback_count"), 5, 0, 10)
    result["max_headhunter_share"] = _int(result.get("max_headhunter_share"), 20, 0, 100)
    result["headhunter_free_top_n"] = _int(result.get("headhunter_free_top_n"), 3, 0, 10)
    return result


def save_candidate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    cleaned = {
        "cities": _list(profile.get("cities")),
        "target_roles": _list(profile.get("target_roles")),
        "salary_upper_floor": normalise_salary_floor(profile.get("salary_upper_floor", DEFAULT_SALARY_UPPER_FLOOR)),
        "excluded_keywords": _list(profile.get("excluded_keywords")),
        "confirmed_skills": _list(profile.get("confirmed_skills")),
        "confirmed_achievements": _list(profile.get("confirmed_achievements")),
        "strict_matching": _bool(profile.get("strict_matching"), True),
        "exclude_staffing_agencies": _bool(profile.get("exclude_staffing_agencies"), True),
        "priority_threshold": _int(profile.get("priority_threshold"), 82, 70, 95),
        "consider_threshold": _int(profile.get("consider_threshold"), 75, 50, 94),
        "minimum_priority_jobs": _int(profile.get("minimum_priority_jobs"), 15, 0, 30),
        "cautious_fallback_count": _int(profile.get("cautious_fallback_count"), 5, 0, 10),
        "max_headhunter_share": _int(profile.get("max_headhunter_share"), 20, 0, 100),
        "headhunter_free_top_n": _int(profile.get("headhunter_free_top_n"), 3, 0, 10),
    }
    cleaned["consider_threshold"] = min(cleaned["consider_threshold"], cleaned["priority_threshold"])
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
        mapped = ROLE_QUERY_MAP.get(role, (role,))
        queries.extend(mapped)
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
