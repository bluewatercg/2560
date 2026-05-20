#!/usr/bin/env python3
"""Runner for rebuild_indicator jobs.

Replaces subprocess.run with Popen + stdout parsing so that
rebuild_technical_indicator.py progress lines are relayed to
MySQL job_execution in real time.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.job_orchestrator import update_job_execution

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    p = argparse.ArgumentParser(description="Run technical_indicator rebuild as background job")
    p.add_argument("--job-id", type=int, default=int(os.getenv("JOB_ID", "0")))
    p.add_argument("--batch-id", type=int, default=int(os.getenv("IMPORT_BATCH_ID", "0")))
    p.add_argument("--market", default=os.getenv("MARKET", "sh60"))
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--periods", default=os.getenv("PERIODS", "daily,5m,30m"))
    p.add_argument("--limit-codes", type=int, default=int(os.getenv("LIMIT_CODES", "0")) or None)
    p.add_argument("--commit-every", type=int, default=int(os.getenv("COMMIT_EVERY", "50")))
    p.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "4")))
    return p.parse_args()


# Match lines like: "daily: processed 50/1704, inserted=1949"
_RE_PROGRESS = re.compile(r"^(daily|5m|30m):\s+processed\s+(\d+)/(\d+),\s+inserted=(\d+)")

# Match lines like: "codes=1704"
_RE_CODES = re.compile(r"^codes=(\d+)")

# Match lines like: "[OK] daily inserted: 66156"
_RE_OK = re.compile(r"^\[OK\]\s+(daily|5m|30m)\s+inserted:\s+(\d+)")


def main():
    a = parse_args()
    if not a.job_id or not a.batch_id:
        raise RuntimeError("job-id and batch-id are required")

    with SessionLocal() as db:
        db.execute(text("""
            UPDATE data_import_batch
            SET status='running', message=:msg, updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "msg": f"running rebuild_indicator job #{a.job_id}"})
        update_job_execution(
            db, a.job_id, status="running",
            progress_current=0, progress_total=0,
            success_count=0, failed_count=0,
            message=f"rebuild indicators started market={a.market}, periods={a.periods}",
        )
        db.commit()

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "rebuild_technical_indicator.py"),
        "--start", a.start,
        "--end", a.end,
        "--market-type", a.market,
        "--periods", a.periods,
        "--commit-every", str(a.commit_every),
    ]
    if a.limit_codes:
        cmd.extend(["--limit-codes", str(a.limit_codes)])

    # Shared state between reader and reporter threads
    _lock = threading.Lock()
    _period_codes: dict[str, int] = {}   # period -> total codes (from codes=N lines)
    _period_done: dict[str, int] = {}    # period -> codes completed (set on [OK])
    _period_progress: dict[str, int] = {} # period -> processed count (from processed X/Y)
    _current_period = ""
    _inserted = 0
    _proc_line_count = 0

    def _codes_done() -> int:
        """Sum of codes completed across all periods."""
        total = 0
        with _lock:
            for p in _period_codes:
                if p in _period_done:
                    total += _period_done[p]
                elif p in _period_progress:
                    total += _period_progress[p]
        return total

    def _codes_total() -> int:
        with _lock:
            return sum(_period_codes.values())

    def _reader(pipe, log_path):
        """Read subprocess output, write to log file, parse progress lines."""
        nonlocal _current_period, _inserted, _proc_line_count
        with open(log_path, "wb") as f:
            for line in iter(pipe.readline, b""):
                f.write(line)
                try:
                    text_line = line.decode("utf-8", errors="replace").strip()
                except Exception:
                    continue

                m = _RE_CODES.match(text_line)
                if m:
                    count = int(m.group(1))
                    with _lock:
                        if _current_period:
                            _period_codes[_current_period] = count
                        # Don't overwrite if we just finished this period
                    continue

                m = _RE_PROGRESS.match(text_line)
                if m:
                    period = m.group(1)
                    processed = int(m.group(2))
                    ins = int(m.group(4))
                    with _lock:
                        _current_period = period
                        _period_codes.setdefault(period, 0)
                        # Only update if this is a new progress value for this period
                        _period_progress[period] = processed
                        _inserted = ins
                        _proc_line_count += 1
                    continue

                m = _RE_OK.match(text_line)
                if m:
                    period = m.group(1)
                    with _lock:
                        # Mark this period as fully done with its total codes
                        if period in _period_codes:
                            _period_done[period] = _period_codes[period]
                        # Clear progress for this period to avoid double-counting
                        _period_progress.pop(period, None)
                    continue

    def _reporter(stop_event: threading.Event):
        """Periodically update MySQL with current progress."""
        last_reported = 0
        while not stop_event.wait(2):
            done = _codes_done()
            total = _codes_total()
            cur_period = _current_period
            ins = _inserted

            # Only update if progress has advanced
            if done == last_reported and done == 0:
                continue

            try:
                with SessionLocal() as db:
                    msg = f"{cur_period}: {done}/{total} (inserted={ins})" if cur_period else f"processing {done}/{total}"
                    update_job_execution(
                        db, a.job_id, status="running",
                        progress_current=done, progress_total=total,
                        success_count=len(_period_done), failed_count=0,
                        current_code=cur_period or "",
                        message=msg,
                    )
                    db.commit()
                    last_reported = done
            except Exception as e:
                print(f"[reporter] MySQL update failed: {e}", flush=True)

    log_path = PROJECT_ROOT / "logs" / f"job_{a.job_id}.rebuild.log"
    log_path.parent.mkdir(exist_ok=True)

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    stop_report = threading.Event()
    reader_thread = threading.Thread(target=_reader, args=(proc.stdout, log_path), daemon=True)
    reporter_thread = threading.Thread(target=_reporter, args=(stop_report,), daemon=True)
    reader_thread.start()
    reporter_thread.start()

    rc = proc.wait()
    reader_thread.join(timeout=5)
    stop_report.set()
    reporter_thread.join(timeout=3)

    # Final counts
    done = _codes_done()
    total = _codes_total()
    periods_completed = len(_period_done)
    periods_expected = len([p for p in a.periods.split(",") if p.strip()])

    status = "success" if rc == 0 else "failed"
    message = f"rebuild_indicator {status} rc={rc}, market={a.market}, periods={a.periods}"

    with SessionLocal() as db:
        db.execute(text("""
            UPDATE data_import_batch
            SET status=:status, finished_at=NOW(), message=:message, updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "status": status, "message": message})
        update_job_execution(
            db, a.job_id, status=status,
            progress_current=total, progress_total=total,
            success_count=periods_completed, failed_count=0 if rc == 0 else periods_expected,
            message=message, finished=True,
        )
        db.commit()

    # 更新 workspace_status：指标重建后刷新对应market的指标记录
    if status == "success":
        from app.services.workspace_service import refresh_market_from_db
        from app.db.session import SessionLocal as _DB
        periods = [p.strip() for p in a.periods.split(",") if p.strip()]
        actual_market = a.market or "all"
        if actual_market == "all":
            for m in ["sh60", "sh68", "sz00", "sz30"]:
                with _DB() as db:
                    refresh_market_from_db(db, m, periods=periods)
        else:
            with _DB() as db:
                refresh_market_from_db(db, actual_market, periods=periods)

    raise SystemExit(rc)


if __name__ == "__main__":
    main()
