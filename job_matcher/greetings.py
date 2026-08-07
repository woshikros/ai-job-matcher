from __future__ import annotations

import hashlib
from typing import Any

from .candidate_profile import get_candidate_profile, profile_facts

FORBIDDEN = ("熟练Python", "精通Python", "独立编写复杂生产代码", "资深软件工程师", "全栈开发专家")

def _focus(job: dict[str, Any]) -> str:
    values = job.get("greeting_focus") or job.get("matched") or []
    return str(values[0]).strip()[:20] if values else "岗位核心职责"

def _fit(text: str) -> str:
    if len(text) < 100: text = text.rstrip("。") + "，可进一步提供对应项目职责、实施过程与交付结果。"
    if len(text) > 130: text = text[:124].rstrip("，。；、") + "，期待沟通。"
    return text

def generate_local_greeting(job: dict[str, Any], version: int = 1) -> str:
    if str(job.get("recruiter_type") or "unknown") == "headhunter": return generate_headhunter_greeting(job, version)
    profile = get_candidate_profile(); skills = list(profile.get("confirmed_skills", [])); outputs = list(profile.get("confirmed_achievements", []))
    if not skills or not outputs: raise ValueError("请先在求职档案中确认技能和项目成果")
    focus = _focus(job); seed = int(hashlib.sha256(f"{job.get('job_id')}|{version}".encode()).hexdigest(), 16)
    selected = skills[seed % len(skills):] + skills[:seed % len(skills)]
    text = f"您好，我具备{'、'.join(selected[:4])}等能力，已完成{outputs[seed % len(outputs)][:35]}。岗位重点是{focus}，与我在需求拆解、方案设计和交付推进方面的实践相关，希望进一步沟通岗位场景与职责。"
    text = _fit(text); _validate(text, list(profile_facts(profile)), focus); return text

def generate_headhunter_greeting(job: dict[str, Any], version: int = 1) -> str:
    profile = get_candidate_profile(); confirmed = list(profile_facts(profile))
    if not confirmed: raise ValueError("请先在求职档案中确认技能和项目成果")
    selected = (list(profile.get("confirmed_skills", []))[:5] + list(profile.get("confirmed_achievements", []))[:2])[:7]
    focus = _focus(job); text = "硬指标清单：" + "；".join(str(item)[:24] for item in selected)
    text += f"。与岗位要求的{focus}直接相关，可提供对应项目职责、实施过程和交付结果。若基础条件匹配，欢迎沟通具体岗位要求。"
    text = _fit(text); _validate(text, confirmed, focus, headhunter=True); return text

def _validate(text: str, facts: list[str], focus: str, headhunter: bool = False) -> None:
    if not 100 <= len(text) <= 130: raise ValueError("招呼语长度必须为100—130字")
    if headhunter and not text.startswith("硬指标清单："): raise ValueError("猎头话术格式不正确")
    if not any(str(fact).lower() in text.lower() for fact in facts): raise ValueError("招呼语缺少已确认事实")
    if focus not in text: raise ValueError("招呼语缺少岗位重点")
    if any(item.lower() in text.lower() for item in FORBIDDEN): raise ValueError("招呼语包含未经确认的能力")
