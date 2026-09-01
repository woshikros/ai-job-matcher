from __future__ import annotations

from typing import Any

from .liepin_bridge import LiepinBridgeError, fetch_liepin_chat_history, fetch_liepin_chat_overview
from .storage import (
    get_conversation, get_conversation_statistics, record_conversation_sync,
    replace_conversation_threads, search_conversations, upsert_conversation_messages,
    upsert_conversation_threads,
)


class ConversationSyncError(RuntimeError):
    def __init__(self, message: str, code: str = "CONVERSATION_SYNC_FAILED") -> None:
        super().__init__(message)
        self.code = code


def _validate_overview(threads: list[dict[str, Any]]) -> None:
    if not threads:
        raise ConversationSyncError("未读取到猎聘会话列表", "LIEPIN_CHAT_READ_FAILED")
    meaningful = sum(bool(item.get("job_name") or item.get("last_message_at") or int(item.get("unread_count") or 0)) for item in threads)
    online = sum("在线" in str(item.get("last_message") or "") for item in threads)
    if meaningful == 0 and online * 2 >= len(threads):
        raise ConversationSyncError("当前识别到的是联系人目录，不是真实会话列表；请打开猎聘沟通面板后重试", "LIEPIN_NOT_CONVERSATION_LIST")
    for item in threads:
        if item.get("company") and item.get("company") == item.get("last_message"):
            item["company"] = ""


def sync_liepin_overview(max_threads: int = 60) -> dict[str, Any]:
    try:
        payload = fetch_liepin_chat_overview(max_threads=max_threads, wait_for_extension=5)
        threads = payload.get("threads") or []
        _validate_overview(threads)
        written = replace_conversation_threads("liepin", threads)
        record_conversation_sync("liepin", status="ok", thread_count=written)
        return {"source": "liepin", "thread_count": written, "threads": threads}
    except (LiepinBridgeError, ConversationSyncError) as exc:
        record_conversation_sync("liepin", status="failed", error=str(exc))
        if isinstance(exc, ConversationSyncError):
            raise
        raise ConversationSyncError(str(exc), exc.code) from exc


def sync_liepin_history(thread_id: str, limit: int = 30) -> dict[str, Any]:
    existing = get_conversation("liepin", thread_id)
    if not existing:
        raise ConversationSyncError("请先同步猎聘沟通列表，再读取该会话", "THREAD_NOT_FOUND")
    try:
        payload = fetch_liepin_chat_history(thread_id, limit=limit, wait_for_extension=5)
        messages = payload.get("messages") or []
        written = upsert_conversation_messages("liepin", thread_id, messages)
        context = payload.get("thread")
        if isinstance(context, dict):
            context = {**existing, **{key: value for key, value in context.items() if value not in (None, "")}}
            context["thread_id"] = thread_id
            upsert_conversation_threads("liepin", [context])
        statistics = get_conversation_statistics()
        record_conversation_sync(
            "liepin", status="ok", thread_count=len(search_conversations(source="liepin")),
            message_count=statistics["messages"],
        )
        return {"source": "liepin", "thread_id": thread_id, "message_count": written}
    except LiepinBridgeError as exc:
        record_conversation_sync("liepin", status="failed", error=str(exc))
        raise ConversationSyncError(str(exc), exc.code) from exc
