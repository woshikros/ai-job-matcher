from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class LiepinCliError(RuntimeError):
    pass


def search_jobs(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """通过官方 CLI 搜索职位；仅执行搜索，不执行投递。"""
    payload = {key: value for key, value in filters.items() if value not in (None, "")}
    with tempfile.TemporaryDirectory(prefix="liepin-search-") as directory:
        input_path = Path(directory) / "search.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        command = [_cli_executable(), "job", "search", "--input", str(input_path), "--output", "json"]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=45)
        except FileNotFoundError as exc:
            raise LiepinCliError("没有找到 liepin-cli。请先按 README 安装猎聘官方 CLI。") from exc
        except subprocess.TimeoutExpired as exc:
            raise LiepinCliError("猎聘查询超时，请稍后重试。") from exc
    if completed.returncode != 0:
        detail = _decode(completed.stderr or completed.stdout).strip()
        raise LiepinCliError(f"猎聘 CLI 查询失败：{detail[-500:]}")
    try:
        data = json.loads(_decode(completed.stdout))
    except json.JSONDecodeError as exc:
        raise LiepinCliError("猎聘 CLI 没有返回可识别的结果，请执行 liepin-cli job search --help 检查安装。") from exc
    return _find_job_list(data)


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for encoding in ("utf-8", "gb18030"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            pass
    return value.decode("utf-8", errors="replace")


def _cli_executable() -> str:
    """优先使用当前虚拟环境中的 CLI，避免依赖系统 PATH。"""
    executable_name = "liepin-cli.exe" if sys.platform == "win32" else "liepin-cli"
    venv_executable = Path(sys.executable).parent / executable_name
    if venv_executable.exists():
        return str(venv_executable)
    system_executable = shutil.which("liepin-cli")
    if system_executable:
        return system_executable
    return executable_name


def _find_job_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("data", "items", "list", "jobs", "jobList", "result"):
        candidate = data.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            found = _find_job_list(candidate)
            if found:
                return found
    return []
