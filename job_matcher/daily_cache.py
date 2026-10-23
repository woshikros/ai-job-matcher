import hashlib
import json
import threading
from copy import deepcopy
from pathlib import Path
from .runtime_files import atomic_json


class CachedReadBlocked(RuntimeError):
    pass


class CachedReads:
    """Per-day checkpoints. Only confirmed successful reads are reused."""
    def __init__(self, path: Path, *, retry_failed: bool = False):
        self.path = path
        self.lock = threading.Lock()
        self.items = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        self.attempt_path = path.with_name(path.stem + '-attempts.json')
        self.attempts = json.loads(self.attempt_path.read_text(encoding='utf-8')) if self.attempt_path.exists() else {}
        self.retry_failed = retry_failed

    def call(self, key, read):
        digest = hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            if digest in self.items: return deepcopy(self.items[digest])
            previous = self.attempts.get(digest)
            if previous and not self.retry_failed:
                raise CachedReadBlocked(f"该读取已有失败或中断记录，不自动重访：{previous.get('error') or previous.get('status')}")
            self.attempts[digest] = {'status': 'running'}
            atomic_json(self.attempt_path, self.attempts)
        try:
            value = read()
        except BaseException as exc:
            with self.lock:
                self.attempts[digest] = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
                atomic_json(self.attempt_path, self.attempts)
            raise
        with self.lock:
            self.items[digest] = value
            atomic_json(self.path, self.items)
            self.attempts[digest] = {'status': 'complete'}
            atomic_json(self.attempt_path, self.attempts)
        return deepcopy(value)
