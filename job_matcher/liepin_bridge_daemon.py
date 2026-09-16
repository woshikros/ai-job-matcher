from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any

from aiohttp import WSMsgType, web

from .liepin_bridge import BRIDGE_HOST, BRIDGE_PORT, PID_PATH


def _usable_result(result: Any, action: str) -> bool:
    if not isinstance(result, dict) or not result.get("ok"):
        return False
    data = result.get("data") or {}
    field = "messages" if action == "extract_liepin_chat_history" else "threads"
    return isinstance(data, dict) and isinstance(data.get(field), list) and bool(data[field]) and not any(
        data.get(key) for key in ("error", "login_required", "security_check")
    )


async def choose_liepin_connection(targets, payload, dispatch):
    """Only try another profile when no page was read. Never fan out UI reads."""
    last = {'ok': False, 'error': 'No extension returned a usable result'}
    for target in targets:
        last = await dispatch(target, payload)
        if not isinstance(last, dict):
            return {'ok':False, 'error':'Invalid extension result'}
        data = last.get('data') or {}
        if isinstance(data, dict) and any(data.get(k) for k in ('security_check', 'login_required', 'environment_risk')):
            return last
        if last.get('ok'):
            return last
        error = str(last.get('error') or '')
        if not any(marker in error for marker in ('Liepin chat tab required', '请先在Chrome中打开并登录猎聘', 'Unsupported command')):
            return last
    return last


async def run_daemon() -> None:
    extensions: dict[str, dict[str, Any]] = {}
    changed = asyncio.Event()
    pending: dict[str, asyncio.Future[Any]] = {}
    started_at = time.time()

    async def status(_: web.Request) -> web.Response:
        ordered = sorted(extensions.values(), key=lambda item: float(item["connected_at"]), reverse=True)
        versions = sorted({str(item.get("version") or "") for item in ordered if item.get("version")})
        return web.json_response({
            "ok": True, "extension_connected": bool(ordered),
            "extension_version": str(ordered[0].get("version") or "") if ordered else "",
            "extension_connections": len(ordered), "extension_versions": versions,
            "pid": os.getpid(), "uptime": int(time.time() - started_at),
        })

    async def dispatch(target: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        command_id = f"{payload['id']}-{uuid.uuid4().hex[:10]}"
        future = asyncio.get_running_loop().create_future()
        pending[command_id] = future
        try:
            await target["ws"].send_json({**payload, "id": command_id})
            return await asyncio.wait_for(future, timeout=30)
        except (asyncio.TimeoutError, ConnectionError, RuntimeError) as exc:
            return {"ok": False, "error": f"Extension command failed: {type(exc).__name__}"}
        finally:
            pending.pop(command_id, None)

    async def command(request: web.Request) -> web.Response:
        if not extensions:
            return web.json_response({"ok": False, "error": "Extension not connected"}, status=503)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        action = str(payload.get("action") or "")
        if action not in {"extract_liepin_chat_overview", "extract_liepin_chat_history", "extract_liepin_detail"} or not payload.get("id"):
            return web.json_response({"ok": False, "error": "Unsupported command"}, status=400)
        targets = sorted(extensions.values(), key=lambda item: float(item["connected_at"]), reverse=True)
        return web.json_response(await choose_liepin_connection(targets, payload, dispatch))

    async def extension_ws(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        connection_id = uuid.uuid4().hex
        extensions[connection_id] = {"ws": ws, "version": "", "connected_at": time.time()}
        changed.set()
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                data = json.loads(message.data)
                if data.get("type") == "hello":
                    extensions[connection_id]["version"] = str(data.get("version") or "")
                    continue
                if data.get("type") == "keepalive":
                    continue
                command_id = str(data.get("id") or "")
                if command_id in pending and not pending[command_id].done():
                    pending[command_id].set_result(data)
        finally:
            extensions.pop(connection_id, None)
            changed.set()
        return ws

    app = web.Application(client_max_size=64 * 1024)
    app.router.add_get("/status", status)
    app.router.add_post("/command", command)
    app.router.add_get("/ext", extension_ws)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, BRIDGE_HOST, BRIDGE_PORT).start()
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    try:
        await asyncio.Event().wait()
    finally:
        PID_PATH.unlink(missing_ok=True)
        await runner.cleanup()


def main() -> None:
    try:
        asyncio.run(run_daemon())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
