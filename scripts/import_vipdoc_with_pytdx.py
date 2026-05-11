#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vipdoc 行情导入工具。

支持：
- 通达信/中金 vipdoc 日线 lday -> daily_kline
- 通达信/中金 vipdoc 5m fzline -> minute_kline_period(period='5m')
- 多线程导入
- 写入 data_import_file 明细
- 更新 stock_calc_status.last_import_at

注意：本脚本只导入行情文件，不触发 2560 / 2568 计算。
"""
from __future__ import annotations

import argparse
import struct
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd
from sqlalchemy import text

try:
    from pytdx.reader import TdxDailyBarReader, TdxLCMinBarReader
except Exception:  # pragma: no cover
    TdxDailyBarReader = None
    TdxLCMinBarReader = None

from app.db.session import SessionLocal

SOURCE = "vipdoc"


def _norm_market(market: str) -> str:
    return (market or "sh").lower().strip()


def _side_from_market(market: str) -> str:
    m = _norm_market(market)
    return "sh" if m.startswith("sh") else "sz" if m.startswith("sz") else m


def code_from_filename(path: Path, market: str) -> str:
    name = path.stem.lower()
    digits = "".join(c for c in name if c.isdigit())
    if len(digits) < 6:
        raise ValueError(f"Cannot parse stock code from file name: {path.name}")
    side = _side_from_market(market)
    return f"{side}.{digits[-6:]}"


def _file_match(path: Path, market: str) -> bool:
    name = path.name.lower()
    m = _norm_market(market)
    if m == "sh":
        return name.startswith("sh")
    if m == "sz":
        return name.startswith("sz")
    if m == "sh60":
        return name.startswith("sh60")
    if m == "sh68":
        return name.startswith("sh68")
    if m == "sz00":
        return name.startswith("sz00")
    if m == "sz30":
        return name.startswith("sz30")
    return name.startswith("sh") or name.startswith("sz")


def _date_int(v) -> int:
    return int(pd.to_datetime(v).strftime("%Y%m%d"))


def _minute_int(v) -> int:
    return int(pd.to_datetime(v).strftime("%Y%m%d%H%M%S"))


def _start_day_i(start: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(start).strftime("%Y%m%d")) if start else None


def _end_day_i(end: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(end).strftime("%Y%m%d")) if end else None


def _start_min_i(start: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(start).strftime("%Y%m%d000000")) if start else None


def _end_min_i(end: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(end).strftime("%Y%m%d235959")) if end else None


def _volume(row) -> float:
    for k in ("volume", "vol", "amount_volume"):
        if k in row and pd.notna(row[k]):
            return float(row[k])
    return 0.0


def _amount(row) -> float:
    for k in ("amount", "money"):
        if k in row and pd.notna(row[k]):
            return float(row[k])
    return 0.0


def _scan_dirs(root: Path, market: str, import_type: str) -> list[Path]:
    side = _side_from_market(market)
    base = root / side
    t = (import_type or "all").lower()
    dirs: list[Path] = []
    if t in ("all", "lday", "daily"):
        dirs.append(base / "lday")
    if t in ("all", "5m", "lc5", "fzline"):
        dirs.append(base / "fzline")
    return [d for d in dirs if d.exists() and d.is_dir()]


def scan_vipdoc_files(source_dir: str, market: str = "sh", import_type: str = "all") -> dict:
    root = Path(source_dir)
    scan_dirs = _scan_dirs(root, market, import_type) if root.exists() else []
    files: list[Path] = []
    for d in scan_dirs:
        dtype = d.name.lower()
        if dtype == "lday":
            candidates = list(d.glob("*.day"))
        elif dtype == "fzline":
            candidates = list(d.glob("*.lc5"))
        else:
            candidates = list(d.iterdir())
        for p in candidates:
            if p.is_file() and _file_match(p, market):
                files.append(p)
    files = sorted(set(files), key=lambda x: str(x))
    return {
        "source_dir": str(root),
        "market": market,
        "import_type": import_type,
        "scan_dirs": [str(x) for x in scan_dirs],
        "total_files": len(files),
        "files": [str(x) for x in files],
    }


def _read_daily(path: Path) -> pd.DataFrame:
    if path.name.lower().startswith("sh68"):
        df = _read_daily_binary(path)
    elif TdxDailyBarReader is None:
        raise RuntimeError("pytdx is not installed or TdxDailyBarReader unavailable")
    else:
        reader = TdxDailyBarReader()
        try:
            df = reader.get_df(str(path))
        except NotImplementedError:
            df = _read_daily_binary(path)
    if df is None:
        return pd.DataFrame()
    return df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df.copy()


def _read_daily_binary(path: Path) -> pd.DataFrame:
    rows = []
    record_size = 32
    with path.open("rb") as f:
        content = f.read()
    for offset in range(0, len(content) - record_size + 1, record_size):
        date_i, open_i, high_i, low_i, close_i, amount, volume_i, _reserved = struct.unpack(
            "<IIIIIfII",
            content[offset:offset + record_size],
        )
        rows.append({
            "date": pd.to_datetime(str(date_i), format="%Y%m%d"),
            "open": open_i * 0.01,
            "high": high_i * 0.01,
            "low": low_i * 0.01,
            "close": close_i * 0.01,
            "amount": float(amount),
            "volume": volume_i * 0.01,
        })
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "amount", "volume"])
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["date"])
    return df[["open", "high", "low", "close", "amount", "volume"]]


def _read_lc5(path: Path) -> pd.DataFrame:
    if TdxLCMinBarReader is None:
        raise RuntimeError("pytdx is not installed or TdxLCMinBarReader unavailable")
    reader = TdxLCMinBarReader()
    df = reader.get_df(str(path))
    if df is None:
        return pd.DataFrame()
    return df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df.copy()


def _filter_rows_by_date(rows: list[dict], start_i: Optional[int], end_i: Optional[int], key: str = "date") -> list[dict]:
    out = []
    for r in rows:
        d = int(r[key])
        if start_i is not None and d < start_i:
            continue
        if end_i is not None and d > end_i:
            continue
        out.append(r)
    return out


def _chunks(rows: list[dict], size: int = 1000) -> Iterable[list[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _update_import_file(db, import_file_id: Optional[int], status: str, rows: int = 0, err: Optional[str] = None):
    if not import_file_id:
        return
    db.execute(text("""
        UPDATE data_import_file
        SET status=:status,
            rows_imported=:rows_imported,
            last_error=:err,
            finished_at=NOW(),
            updated_at=NOW()
        WHERE id=:id
    """), {"id": import_file_id, "status": status, "rows_imported": rows, "err": err[:2000] if err else None})


def _mark_import_file_running(db, import_file_id: Optional[int]):
    if not import_file_id:
        return
    db.execute(text("""
        UPDATE data_import_file
        SET status='running',
            started_at=COALESCE(started_at, NOW()),
            updated_at=NOW()
        WHERE id=:id
    """), {"id": import_file_id})


def _touch_stock_import(db, codes: Iterable[str]):
    data = [{"code": c, "strategy_code": "S2560"} for c in sorted(set(codes))]
    if not data:
        return
    db.execute(text("""
        INSERT INTO stock_calc_status (code, strategy_code, last_import_at, updated_at)
        VALUES (:code, :strategy_code, NOW(), NOW())
        ON DUPLICATE KEY UPDATE last_import_at=VALUES(last_import_at), updated_at=NOW()
    """), data)


def _update_import_batch_progress(db, batch_id: Optional[int], rows: int = 0, success_delta: int = 0, failed_delta: int = 0):
    if not batch_id:
        return
    db.execute(text("""
        UPDATE data_import_batch
        SET success_files = success_files + :success_delta,
            failed_files = failed_files + :failed_delta,
            total_rows = total_rows + :rows,
            updated_at = NOW()
        WHERE id=:id
    """), {
        "id": batch_id,
        "rows": rows,
        "success_delta": success_delta,
        "failed_delta": failed_delta,
    })


def _set_import_batch_status(db, batch_id: Optional[int], status: str, message: Optional[str] = None):
    if not batch_id:
        return
    if message is None:
        db.execute(text("""
            UPDATE data_import_batch
            SET status=:status, updated_at=NOW()
            WHERE id=:id
        """), {"id": batch_id, "status": status})
    else:
        db.execute(text("""
            UPDATE data_import_batch
            SET status=:status, message=:message, updated_at=NOW()
            WHERE id=:id
        """), {"id": batch_id, "status": status, "message": message})


def import_daily_file(path: str, market: str, start: Optional[str] = None, end: Optional[str] = None, import_file_id: Optional[int] = None, batch_id: Optional[int] = None) -> dict:
    p = Path(path)
    code = code_from_filename(p, market)
    start_i = _start_day_i(start)
    end_i = _end_day_i(end)
    with SessionLocal() as db:
        try:
            _mark_import_file_running(db, import_file_id)
            db.commit()
            df = _read_daily(p)
            rows: list[dict] = []
            for _, row in df.iterrows():
                d = _date_int(row.get("date") if "date" in row else row.iloc[0])
                rows.append({
                    "code": code,
                    "date": d,
                    "open": float(row.get("open", 0) or 0),
                    "high": float(row.get("high", 0) or 0),
                    "low": float(row.get("low", 0) or 0),
                    "close": float(row.get("close", 0) or 0),
                    "volume": int(_volume(row)),
                    "amount": float(_amount(row)),
                    "source": SOURCE,
                })
            rows = _filter_rows_by_date(rows, start_i, end_i, "date")
            for part in _chunks(rows):
                db.execute(text("""
                    INSERT INTO daily_kline (code, date, open, high, low, close, volume, amount, source)
                    VALUES (:code, :date, :open, :high, :low, :close, :volume, :amount, :source)
                    ON DUPLICATE KEY UPDATE open=VALUES(open), high=VALUES(high), low=VALUES(low),
                        close=VALUES(close), volume=VALUES(volume), amount=VALUES(amount)
                """), part)
            _touch_stock_import(db, [code])
            _update_import_file(db, import_file_id, "success", len(rows))
            _update_import_batch_progress(db, batch_id, rows=len(rows), success_delta=1)
            db.commit()
            return {"ok": True, "file": str(p), "code": code, "rows": len(rows), "type": "lday"}
        except Exception as exc:
            db.rollback()
            err = traceback.format_exc()
            _update_import_file(db, import_file_id, "failed", 0, err)
            _update_import_batch_progress(db, batch_id, failed_delta=1)
            db.commit()
            return {"ok": False, "file": str(p), "code": code, "rows": 0, "type": "lday", "error": str(exc)}


def import_lc5_file(path: str, market: str, start: Optional[str] = None, end: Optional[str] = None, import_file_id: Optional[int] = None, batch_id: Optional[int] = None) -> dict:
    p = Path(path)
    code = code_from_filename(p, market)
    start_i = _start_min_i(start)
    end_i = _end_min_i(end)
    with SessionLocal() as db:
        try:
            _mark_import_file_running(db, import_file_id)
            db.commit()
            df = _read_lc5(p)
            rows: list[dict] = []
            for _, row in df.iterrows():
                dtv = row.get("datetime", None) or row.get("date", None) or row.iloc[0]
                d = _minute_int(dtv)
                rows.append({
                    "code": code,
                    "date": d,
                    "period": "5m",
                    "source": SOURCE,
                    "open": float(row.get("open", 0) or 0),
                    "high": float(row.get("high", 0) or 0),
                    "low": float(row.get("low", 0) or 0),
                    "close": float(row.get("close", 0) or 0),
                    "volume": float(_volume(row)),
                    "amount": float(_amount(row)),
                })
            rows = _filter_rows_by_date(rows, start_i, end_i, "date")
            for part in _chunks(rows):
                db.execute(text("""
                    INSERT INTO minute_kline_period (code, date, period, source, open, high, low, close, volume, amount)
                    VALUES (:code, :date, :period, :source, :open, :high, :low, :close, :volume, :amount)
                    ON DUPLICATE KEY UPDATE open=VALUES(open), high=VALUES(high), low=VALUES(low),
                        close=VALUES(close), volume=VALUES(volume), amount=VALUES(amount)
                """), part)
            _touch_stock_import(db, [code])
            _update_import_file(db, import_file_id, "success", len(rows))
            _update_import_batch_progress(db, batch_id, rows=len(rows), success_delta=1)
            db.commit()
            return {"ok": True, "file": str(p), "code": code, "rows": len(rows), "type": "5m"}
        except Exception as exc:
            db.rollback()
            err = traceback.format_exc()
            _update_import_file(db, import_file_id, "failed", 0, err)
            _update_import_batch_progress(db, batch_id, failed_delta=1)
            db.commit()
            return {"ok": False, "file": str(p), "code": code, "rows": 0, "type": "5m", "error": str(exc)}


def _file_phase(path: str, import_type: str) -> str:
    p = Path(path)
    parent = p.parent.name.lower()
    suffix = p.suffix.lower()
    if import_type in ("lday", "daily"):
        return "daily"
    if import_type in ("5m", "lc5", "fzline"):
        return "5m"
    if parent == "lday" or suffix == ".day":
        return "daily"
    return "5m"


def import_vipdoc_files_parallel(
    files: list[str],
    market: str,
    import_type: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    workers: int = 4,
    batch_id: Optional[int] = None,
    import_file_ids: Optional[dict[str, int]] = None,
    on_result: Optional[Callable[[dict, int, int], None]] = None,
) -> dict:
    workers = max(1, int(workers or 1))
    results = []
    total_files = len(files)
    completed = 0

    def submit_one(f: str):
        iid = import_file_ids.get(f) if import_file_ids else None

        if _file_phase(f, import_type) == "daily":
            return import_daily_file(f, market, start, end, iid, batch_id=batch_id)
        return import_lc5_file(f, market, start, end, iid, batch_id=batch_id)

    def run_phase(phase_name: str, phase_files: list[str]):
        nonlocal completed
        if not phase_files:
            return
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(submit_one, f) for f in phase_files]
            for fut in as_completed(futs):
                r = fut.result()
                r["phase"] = phase_name
                results.append(r)
                completed += 1
                if on_result:
                    on_result(r, completed, total_files)

    daily_files = [f for f in files if _file_phase(f, import_type) == "daily"]
    minute_files = [f for f in files if _file_phase(f, import_type) == "5m"]

    run_phase("daily", daily_files)
    run_phase("5m", minute_files)

    ok = sum(1 for r in results if r.get("ok"))
    failed = len(results) - ok
    rows = sum(int(r.get("rows") or 0) for r in results)
    return {"ok": failed == 0, "total_files": len(results), "success_files": ok, "failed_files": failed, "total_rows": rows, "results": results}


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--market", default="sh")
    ap.add_argument("--import-type", default="lday", choices=["all", "lday", "daily", "5m", "lc5", "fzline"])
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit-files", type=int, default=None)
    return ap.parse_args()


def main():
    a = parse_args()
    scan = scan_vipdoc_files(a.root, a.market, a.import_type)
    files = scan["files"][:a.limit_files] if a.limit_files else scan["files"]
    print(import_vipdoc_files_parallel(files, a.market, a.import_type, a.start, a.end, a.workers))


if __name__ == "__main__":
    main()
