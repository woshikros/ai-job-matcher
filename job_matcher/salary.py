from __future__ import annotations

import re


SALARY_OPTIONS = (0, 15_000, 20_000, 25_000, 30_000, 40_000, 50_000)
DEFAULT_SALARY_UPPER_FLOOR = 20_000


def parse_monthly_salary_upper(value: str | int | None) -> int | None:
    """Return the advertised upper monthly salary in yuan, or None when unknown."""
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip().lower().replace(",", "").replace("，", "")
    if not text or any(term in text for term in ("面议", "薪资不限", "待遇面谈")):
        return None
    text = re.sub(r"[·•]?\s*\d+\s*薪.*$", "", text)
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    upper = max(numbers)
    annual = "年薪" in text or "/年" in text or "每年" in text
    if "万" in text:
        amount = upper * 10_000
    elif "k" in text:
        amount = upper * 1_000
    elif "元" in text or upper >= 1_000:
        amount = upper
    else:
        return None
    if annual:
        amount /= 12
    return int(round(amount))


def salary_meets_upper_floor(value: str | int | None, floor: int) -> bool:
    if floor <= 0:
        return True
    upper = parse_monthly_salary_upper(value)
    return upper is None or upper >= floor


def normalise_salary_floor(value: int | str | None) -> int:
    try:
        floor = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("无效薪资档位") from exc
    if floor not in SALARY_OPTIONS:
        raise ValueError("无效薪资档位")
    return floor
