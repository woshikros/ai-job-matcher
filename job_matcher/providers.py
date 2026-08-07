from __future__ import annotations

from typing import Any, Protocol

PROVIDER_FIELDS = ("source", "sourceJobId", "jobId", "jobName", "company", "location", "salary", "education", "workYears", "industry", "jobDetailUrl", "publishedAt", "deadline", "recruiterName", "recruiterTitle")

class JobProvider(Protocol):
    """Contract implemented by optional read-only job sources."""
    source: str
    def search(self, query: str, city: str, page: int = 1) -> list[dict[str, Any]]: ...
    def detail(self, job: dict[str, Any]) -> str: ...
    def health(self) -> dict[str, Any]: ...

def normalise_provider_job(job: dict[str, Any], source: str) -> dict[str, Any]:
    result = dict(job)
    raw_id = str(result.get("sourceJobId") or result.get("jobId") or result.get("jobDetailUrl") or "")
    if ":" in raw_id and raw_id.split(":", 1)[0] == source:
        raw_id = raw_id.split(":", 1)[1]
    result.update({
        "source": source, "sourceJobId": raw_id, "jobId": f"{source}:{raw_id}" if raw_id else "",
        "jobName": str(result.get("jobName") or result.get("title") or ""),
        "company": str(result.get("company") or result.get("brandName") or ""),
        "location": str(result.get("location") or result.get("city") or ""),
        "salary": str(result.get("salary") or result.get("salaryDesc") or ""),
        "education": str(result.get("education") or result.get("jobDegree") or ""),
        "workYears": str(result.get("workYears") or result.get("jobExperience") or ""),
        "industry": str(result.get("industry") or result.get("brandIndustry") or ""),
        "jobDetailUrl": str(result.get("jobDetailUrl") or result.get("url") or ""),
        "publishedAt": str(result.get("publishedAt") or result.get("publishTime") or result.get("datePosted") or ""),
        "deadline": str(result.get("deadline") or result.get("applicationDeadline") or result.get("endDate") or ""),
        "recruiterName": str(result.get("recruiterName") or result.get("bossName") or result.get("hrName") or ""),
        "recruiterTitle": str(result.get("recruiterTitle") or result.get("bossTitle") or ""),
    })
    return result

def validate_provider_job(job: dict[str, Any]) -> list[str]:
    return [field for field in ("source", "sourceJobId", "jobName", "company", "jobDetailUrl") if not job.get(field)]
