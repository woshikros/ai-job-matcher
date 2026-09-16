"""Bounded detail reads: probe first, retain successes, stop systemic failures."""
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class DetailReads:
    completed: list[tuple[Any, Any]] = field(default_factory=list)
    failures: int = 0
    skipped: int = 0
    reason: str = ""


def read_details(jobs: list, read: Callable, *, on_result: Callable | None = None) -> DetailReads:
    result = DetailReads()
    consecutive_failures = 0
    reasons: list[str] = []
    attempted = 0
    stopped = False

    def consume(job):
        nonlocal attempted, consecutive_failures, stopped
        attempted += 1
        started = time.monotonic()
        event = {'job_id': str(job.get('jobId', '')) if isinstance(job, dict) else str(job)}
        try:
            value = read(job)
        except (RuntimeError, OSError, ValueError) as exc:
            result.failures += 1
            consecutive_failures += 1
            reason = str(exc)[:240]
            if reason not in reasons and len(reasons) < 3:
                reasons.append(reason)
            stopped = stopped or bool(getattr(exc, 'stop_source', False)) or consecutive_failures >= 3
            event.update(ok=False, code=str(getattr(exc, 'code', type(exc).__name__)), reason=reason)
        else:
            consecutive_failures = 0
            result.completed.append((job, value))
            event.update(ok=True, mode=value.get('read_mode', 'cache_or_direct') if isinstance(value, dict) else 'direct')
        event['seconds'] = round(time.monotonic() - started, 3)
        if on_result:
            on_result(event)

    for job in jobs:
        if stopped:
            break
        consume(job)
    result.skipped = len(jobs) - attempted
    result.reason = "；".join(reasons)
    if stopped:
        result.reason += "；连续失败或平台级异常，已提前停止，请核对后再重试"
    return result
