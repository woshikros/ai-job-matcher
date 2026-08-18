from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .recruiting import RECRUITER_TYPES, classify_recruiter, role_family

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "matcher.db"
FEEDBACK_OUTCOMES={"unknown":"未更新","read_no_reply":"已读未回","resume_requested_stalled":"索要简历后无回复","communicating":"沟通中","rejected":"明确不合适","interview":"面试邀约"}
REJECTION_REASONS=("原因未说明","年龄或资历","学历或学校","工作稳定性","行业经验","技术栈或开发深度","项目或交付经验","管理经验或职级","薪资","地点、出差或驻场","岗位方向","其他")
LEGACY_FEEDBACK={"unknown":"unknown","read_no_reply":"read_no_reply","resume_requested_stalled":"replied","communicating":"replied","rejected":"replied","interview":"interview"}


def initialize() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, filters TEXT NOT NULL, results TEXT NOT NULL)")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS job_statuses (
                job_id TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'liepin',
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','applied','dismissed')),
                updated_at TEXT NOT NULL,
                applied_at TEXT
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_job_statuses_fingerprint ON job_statuses(fingerprint)")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS job_sightings (
                source TEXT NOT NULL, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                platform_published_at TEXT NOT NULL DEFAULT '', seen_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(source, job_id, fingerprint)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS daily_reports (
                report_date TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                html_path TEXT NOT NULL,
                summary TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS daily_report_jobs (
                report_date TEXT NOT NULL,
                job_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'liepin',
                fingerprint TEXT NOT NULL,
                rank INTEGER NOT NULL,
                score INTEGER NOT NULL,
                is_supplemental INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                PRIMARY KEY(report_date, job_id),
                FOREIGN KEY(report_date) REFERENCES daily_reports(report_date) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS manual_greetings (
                job_id TEXT NOT NULL, fingerprint TEXT NOT NULL, greeting TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(job_id, fingerprint)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS source_validation_runs (
                source TEXT NOT NULL,
                run_date TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                passed INTEGER NOT NULL,
                search_count INTEGER NOT NULL DEFAULT 0,
                result_count INTEGER NOT NULL DEFAULT 0,
                detail_success INTEGER NOT NULL DEFAULT 0,
                detail_total INTEGER NOT NULL DEFAULT 0,
                duration_seconds REAL NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                preview_path TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(source, run_date)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS source_settings (
                source TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                consecutive_successes INTEGER NOT NULL DEFAULT 0,
                last_status TEXT NOT NULL DEFAULT 'pending',
                last_checked_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT ''
            )"""
        )
        connection.execute("""CREATE TABLE IF NOT EXISTS deep_analyses (
            report_date TEXT NOT NULL, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            analysis TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
            PRIMARY KEY(report_date,job_id))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS skill_observations (
            report_date TEXT NOT NULL, source TEXT NOT NULL, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            skill TEXT NOT NULL, evidence_state TEXT NOT NULL, score INTEGER NOT NULL,
            title TEXT NOT NULL, company TEXT NOT NULL,
            PRIMARY KEY(report_date,source,job_id,fingerprint,skill))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS skill_gap_reports (
            report_date TEXT PRIMARY KEY, generated_at TEXT NOT NULL, source_dates TEXT NOT NULL, payload TEXT NOT NULL)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS recruiter_overrides (
            fingerprint TEXT PRIMARY KEY, recruiter_type TEXT NOT NULL CHECK(recruiter_type IN ('employer','headhunter','unknown')),
            updated_at TEXT NOT NULL)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS application_records (
            job_id TEXT PRIMARY KEY, source TEXT NOT NULL, fingerprint TEXT NOT NULL,
            company TEXT NOT NULL DEFAULT '', job_name TEXT NOT NULL DEFAULT '', role_family TEXT NOT NULL DEFAULT '其他AI岗位',
            recruiter_type TEXT NOT NULL DEFAULT 'unknown' CHECK(recruiter_type IN ('employer','headhunter','unknown')),
            recruiter_name TEXT NOT NULL DEFAULT '', greeting_text TEXT NOT NULL DEFAULT '', greeting_strategy TEXT NOT NULL DEFAULT 'not_recorded',
            job_url TEXT NOT NULL DEFAULT '', score INTEGER NOT NULL DEFAULT 0, applied_at TEXT NOT NULL,
            feedback_status TEXT NOT NULL DEFAULT 'unknown' CHECK(feedback_status IN ('unknown','read_no_reply','replied','interview')),
            note TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_applications_search ON application_records(company,job_name,recruiter_name)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_applications_applied_at ON application_records(applied_at)")
        _migrate_platform_columns(connection)
        _migrate_application_feedback(connection)
        _backfill_job_sightings(connection)
        _backfill_skill_observations(connection)
        _backfill_application_records(connection)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}

def _migrate_application_feedback(connection: sqlite3.Connection) -> None:
    columns=_columns(connection,"application_records")
    for name,definition in {"feedback_outcome":"TEXT NOT NULL DEFAULT 'unknown'","rejection_reasons":"TEXT NOT NULL DEFAULT '[]'","feedback_note":"TEXT NOT NULL DEFAULT ''","feedback_updated_at":"TEXT"}.items():
        if name not in columns: connection.execute(f"ALTER TABLE application_records ADD COLUMN {name} {definition}")
    connection.execute("""UPDATE application_records SET feedback_outcome=CASE feedback_status WHEN 'read_no_reply' THEN 'read_no_reply' WHEN 'replied' THEN 'communicating' WHEN 'interview' THEN 'interview' ELSE 'unknown' END WHERE feedback_outcome='unknown' AND feedback_status!='unknown'""")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_applications_feedback ON application_records(feedback_outcome,applied_at)")


def _migrate_platform_columns(connection: sqlite3.Connection) -> None:
    if "source" not in _columns(connection, "job_statuses"):
        connection.execute("ALTER TABLE job_statuses ADD COLUMN source TEXT NOT NULL DEFAULT 'liepin'")
    if "source" not in _columns(connection, "daily_report_jobs"):
        connection.execute("ALTER TABLE daily_report_jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'liepin'")
    if "applied_at" not in _columns(connection, "job_statuses"):
        connection.execute("ALTER TABLE job_statuses ADD COLUMN applied_at TEXT")
    connection.execute(
        "UPDATE job_statuses SET applied_at=updated_at WHERE status='applied' AND applied_at IS NULL"
    )
    status_rows = connection.execute("SELECT job_id FROM job_statuses WHERE instr(job_id, ':')=0").fetchall()
    for (job_id,) in status_rows:
        connection.execute("UPDATE job_statuses SET job_id=?,source='liepin' WHERE job_id=?", (f"liepin:{job_id}", job_id))
    report_rows = connection.execute("SELECT report_date,job_id,payload FROM daily_report_jobs WHERE instr(job_id, ':')=0").fetchall()
    for report_date, job_id, payload_text in report_rows:
        payload = json.loads(payload_text)
        payload["job_id"] = f"liepin:{job_id}"
        payload["source"] = "liepin"
        payload["source_job_id"] = str(job_id)
        payload.setdefault("duplicate_group", None)
        payload.setdefault("duplicate_sources", [])
        connection.execute(
            "UPDATE daily_report_jobs SET job_id=?,source='liepin',payload=? WHERE report_date=? AND job_id=?",
            (f"liepin:{job_id}", json.dumps(payload, ensure_ascii=False), report_date, job_id),
        )


def _backfill_job_sightings(connection: sqlite3.Connection) -> None:
    if connection.execute("SELECT COUNT(*) FROM job_sightings").fetchone()[0]: return
    rows = connection.execute("SELECT report_date,payload FROM daily_report_jobs ORDER BY report_date,rank").fetchall()
    for report_date, payload_text in rows:
        try:
            item = json.loads(payload_text)
            if item.get("job_id") and item.get("fingerprint"): _record_job_sighting(connection, item, str(report_date))
        except (json.JSONDecodeError, KeyError, TypeError): continue

def _backfill_skill_observations(connection: sqlite3.Connection) -> None:
    if connection.execute("SELECT COUNT(*) FROM skill_observations").fetchone()[0]: return
    rows = connection.execute("SELECT report_date,payload FROM daily_report_jobs ORDER BY report_date,rank").fetchall(); ignored = ("明确要求", "招聘截止", "英语能力", "岗位包含", "现场工作")
    for report_date, payload_text in rows:
        try: item = json.loads(payload_text)
        except (json.JSONDecodeError, TypeError): continue
        matched = {str(value).strip() for value in item.get("matched", []) if str(value).strip()}; gaps = {str(value).strip() for value in item.get("gaps", []) if str(value).strip()}
        for skill in matched | gaps:
            if skill.startswith(ignored): continue
            connection.execute("""INSERT OR IGNORE INTO skill_observations(report_date,source,job_id,fingerprint,skill,evidence_state,score,title,company) VALUES(?,?,?,?,?,?,?,?,?)""",
                (str(report_date), str(item.get("source", "liepin")), str(item.get("job_id", "")), str(item.get("fingerprint", "")), skill, "confirmed" if skill in matched else "missing", int(item.get("score", 0)), str(item.get("name", "")), str(item.get("company", ""))))


def _latest_job_payload(connection: sqlite3.Connection, job_id: str, fingerprint: str) -> dict[str, Any]:
    row = connection.execute("SELECT payload FROM daily_report_jobs WHERE job_id=? AND fingerprint=? ORDER BY report_date DESC LIMIT 1", (job_id, fingerprint)).fetchone()
    if not row: return {}
    try: return json.loads(row[0])
    except (json.JSONDecodeError, TypeError): return {}

def _application_snapshot(connection: sqlite3.Connection, job_id: str, source: str, fingerprint: str) -> dict[str, Any]:
    payload = _latest_job_payload(connection, job_id, fingerprint)
    override = connection.execute("SELECT recruiter_type FROM recruiter_overrides WHERE fingerprint=?", (fingerprint,)).fetchone()
    recruiter_type = str(override[0]) if override else str(payload.get("recruiter_type") or "unknown")
    manual = connection.execute("SELECT greeting FROM manual_greetings WHERE job_id=? AND fingerprint=?", (job_id, fingerprint)).fetchone()
    greeting = str(manual[0]) if manual else str(payload.get("greeting") or "")
    strategy = "not_recorded" if not greeting else ("headhunter_metrics" if recruiter_type == "headhunter" else str(payload.get("greeting_strategy") or "direct_custom"))
    title = str(payload.get("name") or payload.get("jobName") or "")
    return {"job_id": job_id, "source": source, "fingerprint": fingerprint, "company": str(payload.get("company") or "未记录"),
            "job_name": title or "未记录", "role_family": role_family(title), "recruiter_type": recruiter_type,
            "recruiter_name": str(payload.get("recruiter_name") or ""), "greeting_text": greeting, "greeting_strategy": strategy,
            "job_url": str(payload.get("url") or payload.get("jobDetailUrl") or ""), "score": int(payload.get("score") or 0)}

def _write_application_record(connection: sqlite3.Connection, job_id: str, source: str, fingerprint: str, applied_at: str, replace_snapshot: bool) -> None:
    snapshot = _application_snapshot(connection, job_id, source, fingerprint); now = datetime.now().isoformat(timespec="seconds")
    existing = connection.execute("SELECT 1 FROM application_records WHERE job_id=?", (job_id,)).fetchone()
    if existing and not replace_snapshot:
        connection.execute("UPDATE application_records SET active=1,updated_at=? WHERE job_id=?", (now, job_id)); return
    connection.execute("""INSERT INTO application_records(job_id,source,fingerprint,company,job_name,role_family,recruiter_type,recruiter_name,greeting_text,greeting_strategy,job_url,score,applied_at,feedback_status,note,active,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'unknown','',1,?) ON CONFLICT(job_id) DO UPDATE SET source=excluded.source,fingerprint=excluded.fingerprint,
        company=excluded.company,job_name=excluded.job_name,role_family=excluded.role_family,recruiter_type=excluded.recruiter_type,
        recruiter_name=excluded.recruiter_name,greeting_text=excluded.greeting_text,greeting_strategy=excluded.greeting_strategy,
        job_url=excluded.job_url,score=excluded.score,applied_at=excluded.applied_at,feedback_status='unknown',feedback_outcome='unknown',rejection_reasons='[]',feedback_note='',feedback_updated_at=NULL,note='',active=1,updated_at=excluded.updated_at""",
        (snapshot["job_id"],snapshot["source"],snapshot["fingerprint"],snapshot["company"],snapshot["job_name"],snapshot["role_family"],snapshot["recruiter_type"],snapshot["recruiter_name"],snapshot["greeting_text"],snapshot["greeting_strategy"],snapshot["job_url"],snapshot["score"],applied_at,now))

def _backfill_application_records(connection: sqlite3.Connection) -> None:
    for job_id, source, fingerprint, applied_at in connection.execute("SELECT job_id,source,fingerprint,applied_at FROM job_statuses WHERE status='applied' AND applied_at IS NOT NULL").fetchall():
        if not connection.execute("SELECT 1 FROM application_records WHERE job_id=?", (job_id,)).fetchone():
            _write_application_record(connection, str(job_id), str(source), str(fingerprint), str(applied_at), True)

def save_setting(key: str, value: Any) -> None:
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))


def get_setting(key: str, default: Any = None) -> Any:
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def save_search(filters: dict[str, Any], results: list[dict[str, Any]]) -> None:
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute("INSERT INTO searches(filters,results) VALUES(?,?)", (json.dumps(filters, ensure_ascii=False), json.dumps(results, ensure_ascii=False)))


def _source_from_job_id(job_id: str) -> str:
    return job_id.split(":", 1)[0] if ":" in job_id else "liepin"


def set_job_status(job_id: str, fingerprint: str, status: str, source: str | None = None) -> None:
    if status not in {"pending", "applied", "dismissed"}:
        raise ValueError("无效岗位状态")
    initialize()
    now = datetime.now().isoformat(timespec="seconds")
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        existing = connection.execute(
            "SELECT status,applied_at FROM job_statuses WHERE job_id=?", (job_id,)
        ).fetchone()
        applied_at = None
        if status == "applied":
            applied_at = existing[1] if existing and existing[0] == "applied" and existing[1] else now
        connection.execute(
            """INSERT INTO job_statuses(job_id,source,fingerprint,status,updated_at,applied_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 source=excluded.source,
                 fingerprint=excluded.fingerprint,
                 status=excluded.status,
                 updated_at=excluded.updated_at,
                 applied_at=excluded.applied_at""",
            (job_id, source or _source_from_job_id(job_id), fingerprint, status, now, applied_at),
        )
        if status == "applied" and applied_at:
            _write_application_record(connection, job_id, source or _source_from_job_id(job_id), fingerprint, applied_at, not existing or existing[0] != "applied")
        else:
            connection.execute("UPDATE application_records SET active=0,updated_at=? WHERE job_id=?", (now, job_id))


def get_application_statistics(days: int = 14, as_of: date | None = None) -> dict[str, Any]:
    if days < 1:
        raise ValueError("统计天数必须大于0")
    initialize()
    end_date = as_of or date.today()
    start_date = end_date - timedelta(days=days - 1)
    with closing(sqlite3.connect(DB_PATH)) as connection:
        total = int(connection.execute(
            "SELECT COUNT(*) FROM job_statuses WHERE status='applied' AND applied_at IS NOT NULL"
        ).fetchone()[0])
        rows = connection.execute(
            """SELECT substr(applied_at,1,10),COUNT(*)
               FROM job_statuses
               WHERE status='applied' AND applied_at IS NOT NULL
                 AND substr(applied_at,1,10) BETWEEN ? AND ?
               GROUP BY substr(applied_at,1,10)""",
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
    counts = {str(day): int(count) for day, count in rows}
    daily = []
    for offset in range(days):
        item_date = start_date + timedelta(days=offset)
        daily.append({
            "date": item_date.isoformat(),
            "label": item_date.strftime("%m-%d"),
            "count": counts.get(item_date.isoformat(), 0),
        })
    return {
        "today": counts.get(end_date.isoformat(), 0),
        "total": total,
        "days": days,
        "daily": daily,
        "max_daily": max((item["count"] for item in daily), default=0),
        "review_target": 50, "review_available": total >= 50, "review_progress": total,
    }

def set_recruiter_override(fingerprint: str, recruiter_type: str) -> None:
    if recruiter_type not in RECRUITER_TYPES: raise ValueError("无效招聘者类型")
    initialize(); now = datetime.now().isoformat(timespec="seconds")
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute("INSERT INTO recruiter_overrides(fingerprint,recruiter_type,updated_at) VALUES(?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET recruiter_type=excluded.recruiter_type,updated_at=excluded.updated_at", (fingerprint,recruiter_type,now))
        connection.execute("UPDATE application_records SET recruiter_type=?,updated_at=? WHERE fingerprint=?", (recruiter_type,now,fingerprint))

def get_recruiter_overrides(fingerprints: list[str]) -> dict[str,str]:
    if not fingerprints: return {}
    initialize(); placeholders = ",".join("?" for _ in fingerprints)
    with closing(sqlite3.connect(DB_PATH)) as connection:
        rows = connection.execute(f"SELECT fingerprint,recruiter_type FROM recruiter_overrides WHERE fingerprint IN ({placeholders})", fingerprints).fetchall()
    return {str(row[0]):str(row[1]) for row in rows}

def search_application_records(query: str = "", source: str = "all", recruiter_type: str = "all", feedback_status: str = "all", role: str = "all", date_from: str = "", date_to: str = "", rejection_reason: str="all", sort: str="newest") -> list[dict[str,Any]]:
    initialize(); clauses=["active=1"]; values:list[Any]=[]
    if query.strip(): clauses.append("(company LIKE ? OR job_name LIKE ? OR role_family LIKE ? OR recruiter_name LIKE ? OR greeting_text LIKE ? OR feedback_note LIKE ? OR note LIKE ?)"); token=f"%{query.strip()}%"; values.extend([token]*7)
    if source != "all": clauses.append("source=?"); values.append(source)
    if recruiter_type != "all": clauses.append("recruiter_type=?"); values.append(recruiter_type)
    if feedback_status != "all": clauses.append("feedback_outcome=?"); values.append(feedback_status)
    if role != "all": clauses.append("role_family=?"); values.append(role)
    if date_from: clauses.append("substr(applied_at,1,10)>=?"); values.append(date_from)
    if date_to: clauses.append("substr(applied_at,1,10)<=?"); values.append(date_to)
    if rejection_reason!="all": clauses.append("rejection_reasons LIKE ?"); values.append(f'%"{rejection_reason}"%')
    order_by={"newest":"applied_at DESC","oldest":"applied_at ASC","pending":"CASE WHEN feedback_outcome='unknown' AND date(applied_at)<=date('now','-3 day') THEN 0 ELSE 1 END, applied_at ASC"}.get(sort,"applied_at DESC")
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory=sqlite3.Row; rows=connection.execute(f"SELECT * FROM application_records WHERE {' AND '.join(clauses)} ORDER BY {order_by}",values).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        try: item["rejection_reasons"]=json.loads(item.get("rejection_reasons") or "[]")
        except (json.JSONDecodeError,TypeError): item["rejection_reasons"]=[]
        result.append(item)
    return result

def update_application_record(job_id: str, *, feedback_status: str|None=None, note: str|None=None, greeting_text: str|None=None, recruiter_type: str|None=None, feedback_outcome: str|None=None, rejection_reasons: list[str]|None=None, feedback_note: str|None=None) -> dict[str,Any]|None:
    if feedback_outcome is None and feedback_status is not None: feedback_outcome={"unknown":"unknown","read_no_reply":"read_no_reply","replied":"communicating","interview":"interview"}.get(feedback_status)
    if feedback_outcome is not None and feedback_outcome not in FEEDBACK_OUTCOMES: raise ValueError("无效反馈结果")
    clean_reasons=list(dict.fromkeys(str(x).strip() for x in (rejection_reasons or []) if str(x).strip()))
    if any(x not in REJECTION_REASONS for x in clean_reasons): raise ValueError("无效的不合适原因")
    if feedback_outcome=="rejected" and not clean_reasons: raise ValueError("选择明确不合适时，请至少选择一个原因")
    if feedback_outcome is not None and feedback_outcome!="rejected": clean_reasons=[]
    if recruiter_type is not None and recruiter_type not in RECRUITER_TYPES: raise ValueError("无效招聘者类型")
    initialize(); now=datetime.now().isoformat(timespec="seconds"); assignments=["updated_at=?"]; values:list[Any]=[now]
    if feedback_outcome is not None: assignments.extend(["feedback_outcome=?","feedback_status=?","rejection_reasons=?","feedback_updated_at=?"]); values.extend([feedback_outcome,LEGACY_FEEDBACK[feedback_outcome],json.dumps(clean_reasons,ensure_ascii=False),now])
    for column,value in (("note",note),("feedback_note",feedback_note),("greeting_text",greeting_text),("recruiter_type",recruiter_type)):
        if value is not None: assignments.append(f"{column}=?"); values.append(str(value)[:2000] if column in {"note","feedback_note","greeting_text"} else value)
    values.append(job_id)
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute(f"UPDATE application_records SET {','.join(assignments)} WHERE job_id=? AND active=1",values); connection.row_factory=sqlite3.Row
        row=connection.execute("SELECT * FROM application_records WHERE job_id=? AND active=1",(job_id,)).fetchone()
    if not row: return None
    result=dict(row); result["rejection_reasons"]=json.loads(result.get("rejection_reasons") or "[]"); return result

def get_pending_feedback(limit: int=8, as_of: date|None=None) -> dict[str,Any]:
    cutoff=((as_of or date.today())-timedelta(days=3)).isoformat(); initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection:
        connection.row_factory=sqlite3.Row; total=int(connection.execute("SELECT COUNT(*) FROM application_records WHERE active=1 AND feedback_outcome='unknown' AND substr(applied_at,1,10)<=?",(cutoff,)).fetchone()[0]); rows=connection.execute("SELECT * FROM application_records WHERE active=1 AND feedback_outcome='unknown' AND substr(applied_at,1,10)<=? ORDER BY applied_at ASC LIMIT ?",(cutoff,max(0,int(limit)))).fetchall()
    return {"total":total,"cutoff":cutoff,"records":[dict(row) for row in rows]}

def get_application_review(as_of: date|None=None, minimum_group: int=5, minimum_advice: int=20) -> dict[str,Any]:
    reference=as_of or date.today(); mature_before=(reference-timedelta(days=3)).isoformat(); rows=search_application_records(); mature=[row for row in rows if str(row["applied_at"])[:10]<=mature_before]; known=[row for row in mature if row["feedback_outcome"]!="unknown"]
    labels={"source":{"liepin":"猎聘","zhilian":"智联招聘"},"recruiter_type":{"employer":"企业招聘方","headhunter":"猎头","unknown":"待确认"},"greeting_strategy":{"direct_custom":"定制话术","headhunter_metrics":"猎头硬指标话术","not_recorded":"话术未记录"}}
    def metrics(items):
        total=len(items); updated=[row for row in items if row["feedback_outcome"]!="unknown"]; denominator=len(updated); response=sum(row["feedback_outcome"] in {"resume_requested_stalled","communicating","rejected","interview"} for row in updated); progressed=sum(row["feedback_outcome"] in {"communicating","interview"} for row in updated); rejected=sum(row["feedback_outcome"]=="rejected" for row in updated); interview=sum(row["feedback_outcome"]=="interview" for row in updated); rate=lambda x:round(x*100/denominator) if denominator else 0
        return {"total":total,"updated":denominator,"unknown":total-denominator,"response":response,"progressed":progressed,"rejected":rejected,"interview":interview,"response_rate":rate(response),"progress_rate":rate(progressed),"rejection_rate":rate(rejected),"interview_rate":rate(interview),"enough_sample":denominator>=minimum_group}
    groups={}
    for field in ("role_family","source","recruiter_type","greeting_strategy"):
        buckets={}
        for row in mature: buckets.setdefault(str(row[field]),[]).append(row)
        groups[field]=[{"key":key,"label":labels.get(field,{}).get(key,key),**metrics(items)} for key,items in sorted(buckets.items(),key=lambda pair:len(pair[1]),reverse=True)]
    counts={}
    for row in known:
        if row["feedback_outcome"]=="rejected":
            for reason in row.get("rejection_reasons",[]): counts[reason]=counts.get(reason,0)+1
    reasons=[{"reason":reason,"count":count} for reason,count in sorted(counts.items(),key=lambda x:(-x[1],x[0]))]
    return {"available":len(rows)>=50,"advice_ready":len(known)>=minimum_advice,"total":len(rows),"observing":len(rows)-len(mature),"mature_total":len(mature),"updated_mature":len(known),"overall":metrics(mature),"groups":groups,"rejection_reasons":reasons,"minimum_group":minimum_group,"minimum_advice":minimum_advice,"as_of":reference.isoformat()}


def get_manual_greeting(job_id: str, fingerprint: str) -> dict[str,Any]|None:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection:
        row=connection.execute("SELECT greeting,version,created_at,updated_at FROM manual_greetings WHERE job_id=? AND fingerprint=?",(job_id,fingerprint)).fetchone()
    return {"job_id":job_id,"fingerprint":fingerprint,"greeting":str(row[0]),"version":int(row[1]),"created_at":str(row[2]),"updated_at":str(row[3])} if row else None

def save_manual_greeting(job_id: str, fingerprint: str, greeting: str, version: int) -> dict[str,Any]:
    initialize(); now=datetime.now().isoformat(timespec="seconds")
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute("""INSERT INTO manual_greetings(job_id,fingerprint,greeting,version,created_at,updated_at) VALUES(?,?,?,?,?,?)
            ON CONFLICT(job_id,fingerprint) DO UPDATE SET greeting=excluded.greeting,version=excluded.version,updated_at=excluded.updated_at""",(job_id,fingerprint,greeting,version,now,now))
    return get_manual_greeting(job_id,fingerprint) or {}

def delete_manual_greeting(job_id: str, fingerprint: str) -> None:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection, connection: connection.execute("DELETE FROM manual_greetings WHERE job_id=? AND fingerprint=?",(job_id,fingerprint))

def find_report_job(job_id: str, fingerprint: str) -> dict[str,Any]|None:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection:
        row=connection.execute("SELECT payload FROM daily_report_jobs WHERE job_id=? AND fingerprint=? ORDER BY report_date DESC LIMIT 1",(job_id,fingerprint)).fetchone()
    return json.loads(row[0]) if row else None

def get_job_statuses(job_ids: list[str]) -> dict[str, str]:
    if not job_ids:
        return {}
    initialize()
    placeholders = ",".join("?" for _ in job_ids)
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        rows = connection.execute(
            f"SELECT job_id,status FROM job_statuses WHERE job_id IN ({placeholders})", job_ids
        ).fetchall()
    return {str(job_id): str(status) for job_id, status in rows}


def get_excluded_identities(source: str = "liepin") -> tuple[set[str], set[str]]:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        rows = connection.execute(
            "SELECT job_id,fingerprint FROM job_statuses WHERE source=? AND status IN ('applied','dismissed')", (source,)
        ).fetchall()
    return ({str(row[0]) for row in rows}, {str(row[1]) for row in rows})


def save_daily_report(report_date: str, html_path: str, jobs: list[dict[str, Any]], source_health: list[dict[str, Any]] | None = None) -> None:
    initialize()
    generated_at = datetime.now().isoformat(timespec="seconds")
    summary = {
        "count": len(jobs),
        "qualified": sum(1 for item in jobs if int(item.get("score", 0)) >= int(item.get("priority_threshold") or (82 if item.get("score_version") == "v3" else 70)) and not item.get("is_excluded")),
        "supplemental": sum(1 for item in jobs if bool(item.get("is_supplemental")) and not item.get("is_excluded")),
        "excluded": sum(1 for item in jobs if bool(item.get("is_excluded"))),
        "source_health": source_health or [],
        "score_version": jobs[0].get("score_version", "v2") if jobs and all(item.get("score_version") == jobs[0].get("score_version") for item in jobs) else "mixed",
    }
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """INSERT INTO daily_reports(report_date,generated_at,html_path,summary)
               VALUES(?,?,?,?)
               ON CONFLICT(report_date) DO UPDATE SET
                 generated_at=excluded.generated_at,
                 html_path=excluded.html_path,
                 summary=excluded.summary""",
            (report_date, generated_at, html_path, json.dumps(summary, ensure_ascii=False)),
        )
        connection.execute("DELETE FROM daily_report_jobs WHERE report_date=?", (report_date,))
        for rank, item in enumerate(jobs, start=1):
            enriched = _record_job_sighting(connection, item, report_date)
            connection.execute(
                """INSERT INTO daily_report_jobs(report_date,job_id,source,fingerprint,rank,score,is_supplemental,payload)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    report_date,
                    str(enriched["job_id"]),
                    str(enriched.get("source", _source_from_job_id(str(enriched["job_id"])))),
                    str(enriched["fingerprint"]),
                    rank,
                    int(enriched["score"]),
                    1 if enriched.get("is_supplemental") else 0,
                    json.dumps(enriched, ensure_ascii=False),
                ),
            )
            analysis, analysis_error = enriched.get("deep_analysis"), str(enriched.get("deep_analysis_error") or "")
            if analysis or analysis_error:
                connection.execute("""INSERT INTO deep_analyses(report_date,job_id,fingerprint,analysis,error,updated_at)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(report_date,job_id) DO UPDATE SET fingerprint=excluded.fingerprint,
                    analysis=excluded.analysis,error=excluded.error,updated_at=excluded.updated_at""",
                    (report_date, str(enriched["job_id"]), str(enriched["fingerprint"]), json.dumps(analysis or {}, ensure_ascii=False), analysis_error, generated_at))

def save_skill_observations(report_date: str, rows: list[dict[str, Any]]) -> None:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute("DELETE FROM skill_observations WHERE report_date=?", (report_date,))
        for row in rows:
            connection.execute("""INSERT OR REPLACE INTO skill_observations(
                report_date,source,job_id,fingerprint,skill,evidence_state,score,title,company) VALUES(?,?,?,?,?,?,?,?,?)""",
                (report_date, str(row.get("source", "")), str(row.get("job_id", "")), str(row.get("fingerprint", "")),
                 str(row.get("skill", "")), str(row.get("evidence_state", "missing")), int(row.get("score", 0)),
                 str(row.get("title", "")), str(row.get("company", ""))))

def load_recent_skill_observations(report_count: int = 5) -> tuple[list[str], list[dict[str, Any]]]:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection:
        dates = [str(row[0]) for row in connection.execute("SELECT DISTINCT report_date FROM skill_observations ORDER BY report_date DESC LIMIT ?", (report_count,)).fetchall()]
        if not dates: return [], []
        placeholders = ",".join("?" for _ in dates); connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute(f"SELECT * FROM skill_observations WHERE report_date IN ({placeholders})", dates)]
    return dates, rows

def save_skill_gap_report(report_date: str, source_dates: list[str], payload: dict[str, Any]) -> None:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute("""INSERT INTO skill_gap_reports(report_date,generated_at,source_dates,payload) VALUES(?,?,?,?)
            ON CONFLICT(report_date) DO UPDATE SET generated_at=excluded.generated_at,source_dates=excluded.source_dates,payload=excluded.payload""",
            (report_date, datetime.now().isoformat(timespec="seconds"), json.dumps(source_dates, ensure_ascii=False), json.dumps(payload, ensure_ascii=False)))

def load_skill_gap_report(report_date: str | None = None) -> dict[str, Any] | None:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection:
        row = connection.execute("SELECT report_date,generated_at,source_dates,payload FROM skill_gap_reports WHERE report_date=?", (report_date,)).fetchone() if report_date else connection.execute("SELECT report_date,generated_at,source_dates,payload FROM skill_gap_reports ORDER BY report_date DESC LIMIT 1").fetchone()
    return None if not row else {"report_date": str(row[0]), "generated_at": str(row[1]), "source_dates": json.loads(row[2]), **json.loads(row[3])}

def list_skill_gap_report_dates() -> list[str]:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection: return [str(row[0]) for row in connection.execute("SELECT report_date FROM skill_gap_reports ORDER BY report_date DESC").fetchall()]


def _record_job_sighting(connection: sqlite3.Connection, item: dict[str, Any], report_date: str) -> dict[str, Any]:
    enriched = dict(item)
    source = str(enriched.get("source") or _source_from_job_id(str(enriched["job_id"])))
    job_id, fingerprint = str(enriched["job_id"]), str(enriched["fingerprint"])
    published_at = str(enriched.get("published_at") or enriched.get("publishedAt") or "")
    connection.execute(
        """INSERT INTO job_sightings(source,job_id,fingerprint,first_seen,last_seen,platform_published_at,seen_count)
           VALUES(?,?,?,?,?,?,1)
           ON CONFLICT(source,job_id,fingerprint) DO UPDATE SET
             seen_count=CASE WHEN job_sightings.last_seen<>excluded.last_seen THEN job_sightings.seen_count+1 ELSE job_sightings.seen_count END,
             last_seen=excluded.last_seen,
             platform_published_at=CASE WHEN excluded.platform_published_at<>'' THEN excluded.platform_published_at ELSE job_sightings.platform_published_at END""",
        (source, job_id, fingerprint, report_date, report_date, published_at),
    )
    row = connection.execute("SELECT first_seen,last_seen,platform_published_at,seen_count FROM job_sightings WHERE source=? AND job_id=? AND fingerprint=?", (source, job_id, fingerprint)).fetchone()
    enriched.update({"first_seen": row[0], "last_seen": row[1], "published_at": row[2], "seen_count": row[3], "is_new": row[0] == report_date})
    return enriched


def get_job_sightings(job_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not job_ids: return {}
    initialize()
    placeholders = ",".join("?" for _ in job_ids)
    with closing(sqlite3.connect(DB_PATH)) as connection:
        rows = connection.execute(f"SELECT job_id,first_seen,last_seen,platform_published_at,seen_count FROM job_sightings WHERE job_id IN ({placeholders}) ORDER BY last_seen DESC", job_ids).fetchall()
    return {str(row[0]): {"first_seen": str(row[1]), "last_seen": str(row[2]), "published_at": str(row[3]), "seen_count": int(row[4])} for row in rows}


def record_source_validation(source: str, run_date: str, result: dict[str, Any]) -> int:
    initialize()
    checked_at = datetime.now().isoformat(timespec="seconds")
    passed = bool(result.get("passed"))
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.execute(
            """INSERT INTO source_validation_runs(
                   source,run_date,checked_at,passed,search_count,result_count,detail_success,detail_total,
                   duration_seconds,error,preview_path
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source,run_date) DO UPDATE SET
                   checked_at=excluded.checked_at,passed=excluded.passed,search_count=excluded.search_count,
                   result_count=excluded.result_count,detail_success=excluded.detail_success,
                   detail_total=excluded.detail_total,duration_seconds=excluded.duration_seconds,
                   error=excluded.error,preview_path=excluded.preview_path""",
            (source, run_date, checked_at, 1 if passed else 0, int(result.get("search_count", 0)),
             int(result.get("result_count", 0)), int(result.get("detail_success", 0)),
             int(result.get("detail_total", 0)), float(result.get("duration_seconds", 0)),
             str(result.get("error", "")), str(result.get("preview_path", ""))),
        )
        rows = connection.execute(
            "SELECT run_date,passed FROM source_validation_runs WHERE source=? ORDER BY run_date DESC", (source,)
        ).fetchall()
        consecutive = 0
        previous: datetime | None = None
        for date_text, row_passed in rows:
            current = datetime.fromisoformat(str(date_text))
            if not row_passed or (previous and current.date() != _previous_workday(previous.date())):
                break
            consecutive += 1
            previous = current
        enabled = consecutive >= 3
        connection.execute(
            """INSERT INTO source_settings(source,enabled,consecutive_successes,last_status,last_checked_at,last_error)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(source) DO UPDATE SET enabled=excluded.enabled,
                   consecutive_successes=excluded.consecutive_successes,last_status=excluded.last_status,
                   last_checked_at=excluded.last_checked_at,last_error=excluded.last_error""",
            (source, 1 if enabled else 0, consecutive, "ok" if passed else "failed", checked_at,
             str(result.get("error", ""))),
        )
    return consecutive


def _previous_workday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def get_source_health(source: str) -> dict[str, Any]:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection:
        row = connection.execute(
            "SELECT enabled,consecutive_successes,last_status,last_checked_at,last_error FROM source_settings WHERE source=?",
            (source,),
        ).fetchone()
    if not row:
        return {"source": source, "enabled": False, "consecutive_successes": 0, "status": "pending", "error": ""}
    return {"source": source, "enabled": bool(row[0]), "consecutive_successes": int(row[1]),
            "status": str(row[2]), "checked_at": str(row[3]), "error": str(row[4])}


def list_report_dates() -> list[dict[str, Any]]:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        rows = connection.execute(
            "SELECT report_date,generated_at,summary FROM daily_reports ORDER BY report_date DESC"
        ).fetchall()
    return [
        {"report_date": row[0], "generated_at": row[1], **json.loads(row[2])}
        for row in rows
    ]


def load_daily_report(report_date: str | None = None) -> tuple[str | None, list[dict[str, Any]]]:
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        if report_date is None:
            row = connection.execute("SELECT report_date FROM daily_reports ORDER BY report_date DESC LIMIT 1").fetchone()
            if not row:
                return None, []
            report_date = str(row[0])
        rows = connection.execute(
            "SELECT payload FROM daily_report_jobs WHERE report_date=? ORDER BY rank", (report_date,)
        ).fetchall()
    jobs = [json.loads(row[0]) for row in rows]
    statuses = get_job_statuses([str(item["job_id"]) for item in jobs])
    sightings = get_job_sightings([str(item["job_id"]) for item in jobs])
    overrides = get_recruiter_overrides([str(item.get("fingerprint", "")) for item in jobs])
    for item in jobs:
        item["status"] = statuses.get(str(item["job_id"]), "pending")
        item.update(sightings.get(str(item["job_id"]), {}))
        item["is_new"] = item.get("first_seen") == report_date
        if not item.get("recruiter_type"):
            identity=classify_recruiter(item,str(item.get("detail") or "")); item.update({"recruiter_type":identity.recruiter_type,"recruiter_name":identity.name,"recruiter_title":identity.title,"recruiter_evidence":identity.evidence,"greeting_strategy":"headhunter_metrics" if identity.recruiter_type=="headhunter" else "direct_custom"})
        override=overrides.get(str(item.get("fingerprint", "")))
        if override: item["recruiter_type"]=override; item["recruiter_evidence"]="已按人工设置"; item["greeting_strategy"]="headhunter_metrics" if override=="headhunter" else "direct_custom"
        item["greeting_manual"]=False; manual=get_manual_greeting(str(item["job_id"]),str(item["fingerprint"]))
        if manual: item["greeting"]=manual["greeting"]; item["greeting_version"]=manual["version"]; item["greeting_manual"]=True
    return report_date, jobs


def get_report_summary(report_date: str | None) -> dict[str, Any]:
    if not report_date:
        return {}
    initialize()
    with closing(sqlite3.connect(DB_PATH)) as connection:
        row = connection.execute("SELECT summary FROM daily_reports WHERE report_date=?", (report_date,)).fetchone()
    return json.loads(row[0]) if row else {}
