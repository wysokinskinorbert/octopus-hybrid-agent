import json
import time
import os
from pathlib import Path
from dataclasses import asdict, is_dataclass
from datetime import datetime

class SessionLogger:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"session_{timestamp}.jsonl"
        self._write({"event": "session_start", "timestamp": time.time()})

    def log_event(self, event_type: str, content: str, metadata: dict = None):
        entry = {
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat(),
            "type": event_type,
            "content": content,
            "metadata": metadata or {}
        }
        self._write(entry)

    def _write(self, data: dict):
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            # Fallback to stderr if logging fails, but don't crash app
            sys.stderr.write(f"Logger Error: {e}\n")

    def get_log_path(self):
        return str(self.log_file)
