from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "data", "reports", "uploads", "logs"}
TEXT_EXTENSIONS = {".py", ".html", ".md", ".toml", ".json", ".yml", ".yaml", ".ps1", ".cmd", ".txt"}
PRIVATE_EXTENSIONS = {".pdf", ".doc", ".docx", ".db", ".sqlite", ".sqlite3", ".log"}
SECRET_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
SECRET_ASSIGNMENT = re.compile(r"(?<![A-Za-z0-9_])(?:api[_-]?key|token|cookie|password)\s*[:=]\s*['\"]?([^'\"\s]{8,})", re.I)
PLACEHOLDERS = ("replace", "your-", "example", "changeme", "local-key")
ABSOLUTE_PRIVATE_PATHS = (re.compile(r"[A-Za-z]:\\Users\\", re.I), re.compile(r"[A-Za-z]:\\工作\\", re.I))
REQUIRED_IGNORES = {"data/", "reports/", "uploads/", "logs/", "*.db", "*.pdf", "*.docx", ".env", "config/*.local.json"}

def run_checks(release: bool = False) -> list[str]:
    errors = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts): continue
        relative = path.relative_to(ROOT).as_posix()
        if release and path.suffix.lower() in PRIVATE_EXTENSIONS: errors.append(f"发布目录包含私人文件：{relative}")
        if path.suffix.lower() not in TEXT_EXTENSIONS: continue
        try: text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        assigned = [match.group(1) for match in SECRET_ASSIGNMENT.finditer(text)]
        if SECRET_TOKEN.search(text) or any(not any(marker in value.lower() for marker in PLACEHOLDERS) for value in assigned): errors.append(f"疑似密钥或登录信息：{relative}")
        if release and any(pattern.search(text) for pattern in ABSOLUTE_PRIVATE_PATHS): errors.append(f"发布目录包含本机绝对路径：{relative}")
    if release:
        ignore_path = ROOT / ".gitignore"; rules = {line.strip() for line in ignore_path.read_text(encoding="utf-8").splitlines()} if ignore_path.exists() else set()
        for rule in sorted(REQUIRED_IGNORES - rules): errors.append(f".gitignore缺少隐私规则：{rule}")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description="检查岗位面板源码中的隐私与密钥风险"); parser.add_argument("--release", action="store_true"); args = parser.parse_args(); errors = run_checks(args.release)
    if errors: print("\n".join(f"ERROR: {item}" for item in errors)); return 1
    print("Security checks passed."); return 0

if __name__ == "__main__": sys.exit(main())
