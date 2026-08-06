from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_PROFILE: dict[str, list[str]] = {
    "opening_facts": ["AI解决方案", "AI项目", "Agent"],
    "allowed_facts": ["AI解决方案", "AI Agent", "需求分析", "流程拆解", "Workflow", "Skill", "MCP", "API"],
    "tech_facts": ["Workflow", "Skill", "MCP", "API"],
    "output_facts": ["示例业务工作流", "示例Agent原型", "示例Skill"],
    "forbidden_claims": ["精通Python", "熟练Python", "独立编写复杂生产代码", "资深软件工程师", "全栈开发专家"],
    "greeting_context": ["仅使用候选人本机配置中已经确认的真实经历，不得补写或夸大能力"],
}


def profile_path() -> Path:
    return Path(os.getenv("JOB_MATCHER_PROFILE", "config/profile.local.json"))


def load_candidate_profile(path: Path | None = None) -> dict[str, list[str]]:
    selected = path or profile_path()
    if not selected.exists():
        return {key: list(value) for key, value in DEFAULT_PROFILE.items()}
    raw: Any = json.loads(selected.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("候选人配置必须是JSON对象")
    profile: dict[str, list[str]] = {}
    for key, defaults in DEFAULT_PROFILE.items():
        value = raw.get(key, defaults)
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"候选人配置字段 {key} 必须是非空字符串数组")
        profile[key] = [item.strip() for item in value]
    return profile
