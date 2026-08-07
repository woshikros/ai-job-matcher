from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any
from . import storage

TABLES = ("settings", "searches", "job_statuses", "daily_reports", "daily_report_jobs", "manual_greetings", "source_validation_runs", "source_settings", "job_sightings", "deep_analyses", "skill_observations", "skill_gap_reports", "recruiter_overrides", "application_records")
PRIVATE_SETTING_KEYS = {"resume_text", "resume_name", "candidate_profile", "preferences"}

def export_backup() -> dict[str, Any]:
    storage.initialize(); tables: dict[str, list[dict[str, Any]]] = {}
    with closing(sqlite3.connect(storage.DB_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        existing = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in TABLES:
            if table not in existing: continue
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
            if table == "settings": rows = [row for row in rows if row.get("key") not in PRIVATE_SETTING_KEYS]
            tables[table] = rows
    return {"schema_version": 1, "exported_at": datetime.now().isoformat(timespec="seconds"), "tables": tables}

def restore_backup(payload: dict[str, Any]) -> dict[str, int]:
    if payload.get("schema_version") != 1 or not isinstance(payload.get("tables"), dict): raise ValueError("备份文件格式不正确")
    storage.initialize(); restored: dict[str, int] = {}
    with closing(sqlite3.connect(storage.DB_PATH)) as connection, connection:
        for table in TABLES:
            rows = payload["tables"].get(table, [])
            if not isinstance(rows, list) or not rows: continue
            allowed = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}; count = 0
            for raw in rows:
                if not isinstance(raw, dict): continue
                if table == "settings" and raw.get("key") in PRIVATE_SETTING_KEYS: continue
                row = {key: value for key, value in raw.items() if key in allowed}
                if not row: continue
                columns = list(row); placeholders = ",".join("?" for _ in columns)
                connection.execute(f"INSERT OR REPLACE INTO {table}({','.join(columns)}) VALUES({placeholders})", [row[column] for column in columns]); count += 1
            restored[table] = count
    return restored

def parse_backup(raw: bytes) -> dict[str, Any]:
    try: value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError("备份文件不是有效的UTF-8 JSON") from exc
    if not isinstance(value, dict): raise ValueError("备份文件格式不正确")
    return value
