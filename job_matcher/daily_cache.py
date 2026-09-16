import hashlib
import json
import threading
from pathlib import Path
from .runtime_files import atomic_json


class CachedReads:
    """Per-day checkpoints. Only confirmed successful reads are reused."""
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.items = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def call(self, key, read):
        digest = hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            if digest in self.items: return self.items[digest]
        value = read()
        with self.lock:
            self.items[digest] = value
            atomic_json(self.path, self.items)
        return value
