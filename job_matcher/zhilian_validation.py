from __future__ import annotations

import argparse
import html
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from .storage import record_source_validation
from .zhilian_client import ZhilianReadError, fetch_zhilian_detail, search_zhilian_jobs


VALIDATION_QUERIES = ("FDE", "AI解决方案架构师", "AI产品经理")


def run_validation(report_date: str, output_dir: Path = Path("reports")) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "date": report_date, "passed": False, "search_count": 0, "result_count": 0,
        "detail_success": 0, "detail_total": 0, "stable_ids": False,
        "queries": [], "jobs": [], "error": "",
    }
    try:
        unique: dict[str, dict[str, Any]] = {}
        successful_queries = 0
        first_results: list[dict[str, Any]] = []
        for query in VALIDATION_QUERIES:
            jobs = search_zhilian_jobs(query, city="深圳", page=1)
            result["search_count"] += 1
            result["queries"].append({"query": query, "count": len(jobs)})
            if jobs:
                successful_queries += 1
            if query == VALIDATION_QUERIES[0]:
                first_results = jobs
            for job in jobs:
                unique[job["jobId"]] = job
        repeated = search_zhilian_jobs(VALIDATION_QUERIES[0], city="深圳", page=1)
        result["search_count"] += 1
        first_ids = {item["jobId"] for item in first_results}
        repeated_ids = {item["jobId"] for item in repeated}
        required_overlap = min(3, len(first_ids))
        result["stable_ids"] = required_overlap > 0 and len(first_ids & repeated_ids) >= required_overlap
        result["result_count"] = len(unique)
        sample = list(unique.values())[:5]
        result["detail_total"] = len(sample)
        for job in sample:
            preview_job = {key: job.get(key) for key in (
                "jobId", "sourceJobId", "jobName", "company", "location", "salary",
                "education", "workYears", "industry", "jobDetailUrl",
            )}
            result["jobs"].append(preview_job)
            try:
                preview_job["detail"] = fetch_zhilian_detail(job).text
                result["detail_success"] += 1
            except ZhilianReadError as exc:
                preview_job["detail_error"] = f"{exc.code}: {exc}"
                if exc.code == "SECURITY_CHECK":
                    raise
        all_shenzhen = bool(unique) and all("深圳" in str(item.get("location", "")) for item in unique.values())
        result["passed"] = (
            successful_queries >= 2 and len(unique) >= 5 and all_shenzhen
            and result["detail_total"] >= 5 and result["detail_success"] >= 4 and result["stable_ids"]
        )
        if not result["passed"]:
            result["error"] = "未达到深圳搜索、详情成功率或岗位ID稳定性门槛"
    except ZhilianReadError as exc:
        result["error"] = f"{exc.code}: {exc}"
    result["duration_seconds"] = round(time.monotonic() - started, 2)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"zhilian-validation-{report_date}.json"
    html_path = output_dir / f"zhilian-validation-{report_date}.html"
    result["preview_path"] = str(html_path.resolve())
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(_render_preview(result), encoding="utf-8")
    result["consecutive_successes"] = record_source_validation("zhilian", report_date, result)
    return result


def _render_preview(result: dict[str, Any]) -> str:
    status = "通过" if result["passed"] else "未通过"
    rows = "".join(
        f"<tr><td>{html.escape(str(job.get('jobName', '')))}</td><td>{html.escape(str(job.get('company', '')))}</td>"
        f"<td>{html.escape(str(job.get('location', '')))}</td><td>{'成功' if job.get('detail') else '失败'}</td></tr>"
        for job in result.get("jobs", [])
    )
    return f"""<!doctype html><meta charset='utf-8'><title>智联稳定性验证</title>
    <style>body{{font:15px/1.6 system-ui;margin:35px;max-width:900px}}.ok{{color:#087a55}}.bad{{color:#b42318}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px}}</style>
    <h1>智联稳定性验证：<span class='{'ok' if result['passed'] else 'bad'}'>{status}</span></h1>
    <p>{html.escape(result['date'])} · 搜索结果 {result['result_count']} · JD成功 {result['detail_success']}/{result['detail_total']} · ID稳定 {result['stable_ids']}</p>
    <p class='bad'>{html.escape(result.get('error', ''))}</p><table><tr><th>岗位</th><th>公司</th><th>地点</th><th>完整JD</th></tr>{rows}</table>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="智联求职网页只读稳定性验证")
    parser.add_argument("--report-date", default=date.today().isoformat())
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    result = run_validation(args.report_date, args.output_dir)
    print(json.dumps({
        "passed": result["passed"], "result_count": result["result_count"],
        "detail_success": result["detail_success"], "detail_total": result["detail_total"],
        "stable_ids": result["stable_ids"], "consecutive_successes": result["consecutive_successes"],
        "preview_path": result["preview_path"], "error": result["error"],
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
