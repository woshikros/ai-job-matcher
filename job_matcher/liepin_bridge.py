from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 19826
BRIDGE_BASE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PID_PATH = PROJECT_ROOT / "data" / "liepin_bridge.pid"
LOG_PATH = PROJECT_ROOT / "logs" / "liepin_bridge.log"


class LiepinBridgeError(RuntimeError):
    def __init__(self, message: str, code: str = "BRIDGE_ERROR") -> None:
        super().__init__(message)
        self.code = code


def _read_json(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 3.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{BRIDGE_BASE_URL}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LiepinBridgeError("猎聘本机桥接服务未运行", "BRIDGE_NOT_RUNNING") from exc
    return result if isinstance(result, dict) else {}


def bridge_status(*, start: bool = False, wait_seconds: float = 0.0) -> dict[str, Any]:
    if start:
        ensure_bridge_daemon()
    deadline = time.monotonic() + max(wait_seconds, 0)
    while True:
        try:
            return _read_json("/status")
        except LiepinBridgeError:
            if time.monotonic() >= deadline:
                return {"ok": False, "extension_connected": False, "error": "猎聘本机桥接服务未运行"}
            time.sleep(0.25)


def ensure_bridge_daemon() -> None:
    if bridge_status().get("ok"):
        return
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with LOG_PATH.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [sys.executable, "-m", "job_matcher.liepin_bridge_daemon"],
            cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=creationflags,
        )
    if not bridge_status(wait_seconds=5).get("ok"):
        raise LiepinBridgeError("猎聘本机桥接服务启动失败，请查看 logs/liepin_bridge.log", "BRIDGE_START_FAILED")


def _extension_command(action: str, url: str = "https://c.liepin.com/", *, params: dict[str, Any] | None = None, wait_for_extension: float = 30.0) -> dict[str, Any]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (host == "liepin.com" or host.endswith(".liepin.com")):
        raise LiepinBridgeError("桥接只允许读取猎聘HTTPS页面", "BRIDGE_URL_BLOCKED")
    ensure_bridge_daemon()
    deadline = time.monotonic() + max(wait_for_extension, 0)
    while True:
        status = bridge_status()
        if status.get("extension_connected"):
            break
        if time.monotonic() >= deadline:
            raise LiepinBridgeError(
                "猎聘只读扩展尚未连接。请加载 tools/liepin-readonly-extension，并保持已登录的猎聘页签打开",
                "BRIDGE_EXTENSION_DISCONNECTED",
            )
        time.sleep(0.5)
    command = {"id": uuid.uuid4().hex, "action": action, "url": url, "params": params or {}}
    try:
        result = _read_json("/command", method="POST", payload=command, timeout=35)
    except LiepinBridgeError as exc:
        raise LiepinBridgeError("猎聘只读扩展请求超时或已断开", "BRIDGE_COMMAND_FAILED") from exc
    if not result.get("ok"):
        error = str(result.get("error") or "未知错误")
        code = "LIEPIN_TAB_REQUIRED" if "Liepin chat tab required" in error else "BRIDGE_COMMAND_FAILED"
        raise LiepinBridgeError(error, code)
    response = result.get("data") or {}
    if not isinstance(response, dict):
        raise LiepinBridgeError("猎聘扩展返回格式异常", "LIEPIN_INVALID_RESPONSE")
    return response


def _validate_response(response: dict[str, Any], field: str) -> dict[str, Any]:
    if response.get("security_check"):
        raise LiepinBridgeError("猎聘沟通页触发安全验证，已停止读取", "SECURITY_CHECK")
    if response.get("login_required"):
        raise LiepinBridgeError("猎聘登录状态已失效，请先登录候选人端", "LOGIN_REQUIRED")
    if response.get("error"):
        raise LiepinBridgeError(str(response.get("error")), "LIEPIN_CHAT_READ_FAILED")
    if not isinstance(response.get(field) or [], list):
        raise LiepinBridgeError("猎聘会话返回格式异常", "LIEPIN_INVALID_RESPONSE")
    return response


def fetch_liepin_chat_overview(*, max_threads: int = 60, wait_for_extension: float = 30.0) -> dict[str, Any]:
    response = _extension_command(
        "extract_liepin_chat_overview",
        params={"max_threads": max(1, min(int(max_threads), 100))},
        wait_for_extension=wait_for_extension,
    )
    return _validate_response(response, "threads")


def fetch_liepin_chat_history(thread_id: str, *, limit: int = 30, wait_for_extension: float = 30.0) -> dict[str, Any]:
    clean_thread_id = str(thread_id).strip()
    if not re.fullmatch(r"imid-[A-Za-z0-9_%~-]{1,220}", clean_thread_id):
        raise LiepinBridgeError("猎聘会话标识无效", "INVALID_CHAT_ID")
    response = _extension_command(
        "extract_liepin_chat_history",
        params={"thread_id": clean_thread_id, "limit": max(1, min(int(limit), 50))},
        wait_for_extension=wait_for_extension,
    )
    return _validate_response(response, "messages")
