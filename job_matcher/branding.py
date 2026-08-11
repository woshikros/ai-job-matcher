from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path


_ASSET_DIR = Path(__file__).with_name("assets") / "platforms"
_SOURCE_ASSETS = {
    "liepin": ("liepin.ico", "image/x-icon"),
    "zhilian": ("zhilian.ico", "image/x-icon"),
}


@lru_cache(maxsize=1)
def get_source_logos() -> dict[str, str]:
    """Return self-contained data URIs so saved HTML reports work offline."""
    logos: dict[str, str] = {}
    for source, (filename, mime_type) in _SOURCE_ASSETS.items():
        try:
            payload = (_ASSET_DIR / filename).read_bytes()
        except OSError:
            continue
        if payload:
            encoded = base64.b64encode(payload).decode("ascii")
            logos[source] = f"data:{mime_type};base64,{encoded}"
    return logos
