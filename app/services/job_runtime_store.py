from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class JobRuntimeStore:
    """Filesystem-backed runtime state for live job progress and logs."""

    def __init__(self, log_dir: Path | str):
        self.log_dir = Path(log_dir)

    def progress_path(self, job_id: int) -> Path:
        return self.log_dir / f"job_{int(job_id)}.progress.json"

    def log_path(self, job_id: int) -> Path:
        return self.log_dir / f"job_{int(job_id)}.log"

    def ensure_log_file(self, job_id: int) -> Path:
        path = self.log_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    def write_progress(self, job_id: int, progress: dict[str, Any]) -> dict[str, Any]:
        path = self.progress_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "job_id": int(job_id),
            **progress,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)
        return data

    def read_progress(self, job_id: int) -> dict[str, Any] | None:
        path = self.progress_path(job_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None

    def append_log_line(self, job_id: int, line: str) -> None:
        path = self.ensure_log_file(job_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(line.rstrip("\n") + "\n")

    def tail_log(self, job_id: int, n: int) -> list[str]:
        return tail_lines(self.log_path(job_id), n)


class JobProgressReporter:
    """Writes every progress update to disk and throttles durable MySQL flushes."""

    def __init__(
        self,
        job_id: int,
        store: JobRuntimeStore,
        mysql_interval_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.job_id = int(job_id)
        self.store = store
        self.mysql_interval_seconds = mysql_interval_seconds
        self.clock = clock
        self._last_mysql_flush: float | None = None

    def report(self, progress: dict[str, Any], force_mysql: bool = False) -> bool:
        self.store.write_progress(self.job_id, progress)
        now = self.clock()
        if force_mysql or self._last_mysql_flush is None:
            self._last_mysql_flush = now
            return True
        if now - self._last_mysql_flush >= self.mysql_interval_seconds:
            self._last_mysql_flush = now
            return True
        return False


def tail_lines(path: Path, n: int) -> list[str]:
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        block = 4096
        data = b""
        while end > 0 and data.count(b"\n") <= n:
            step = min(block, end)
            end -= step
            f.seek(end)
            data = f.read(step) + data
        return data.decode("utf-8", errors="replace").splitlines()[-n:]
