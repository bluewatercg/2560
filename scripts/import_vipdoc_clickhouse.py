#!/usr/bin/env python3
"""
ClickHouse 行情导入：vipdoc -> daily_kline / minute_kline_period
替代原来的 import_vipdoc_with_pytdx.py 的 MySQL 写入部分。

用法：
    python scripts/import_vipdoc_clickhouse.py --source-dir /data/vipdoc --market sh60 --import-type all
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import struct
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import httpx

try:
    from pytdx.reader import TdxDailyBarReader, TdxLCMinBarReader
except Exception:
    TdxDailyBarReader = None
    TdxLCMinBarReader = None

from app.core.market_scope import market_file_prefixes, normalize_market_scope

logger = logging.getLogger(__name__)

SOURCE = "vipdoc"

# ── ClickHouse config ──────────────────────────────────────────────
CH_HOST = os.getenv("CLICKHOUSE_HOST", "192.168.1.18")
CH_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CH_USER = os.getenv("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CH_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "strategy2560")

CH_URL = f"http://{CH_HOST}:{CH_PORT}"


def _ch_params(query: str) -> dict:
    params = {"query": query, "database": CH_DATABASE, "user": CH_USER}
    if CH_PASSWORD:
        params["password"] = CH_PASSWORD
    return params


def ch_command(query: str) -> str:
    with httpx.Client(timeout=30) as client:
        r = client.post(CH_URL, params=_ch_params(query))
        r.raise_for_status()
        return r.text.strip()


def ch_insert(table: str, rows: list[dict]) -> int:
    """Batch insert via JSONEachRow format."""
    if not rows:
        return 0
    body = "\n".join(json.dumps(row, default=str) for row in rows)
    query = f"INSERT INTO {CH_DATABASE}.{table} FORMAT JSONEachRow"
    params = {"database": CH_DATABASE, "user": CH_USER, "query": query}
    if CH_PASSWORD:
        params["password"] = CH_PASSWORD
    with httpx.Client(timeout=120) as client:
        r = client.post(CH_URL, params=params, content=body.encode("utf-8"),
                       headers={"Content-Type": "application/x-ndjson"})
        r.raise_for_status()
    return len(rows)


def ch_ping() -> bool:
    try:
        with httpx.Client(timeout=5) as client:
            r = client.post(CH_URL, params=_ch_params("SELECT 1"))
            return r.status_code == 200 and r.text.strip() == "1"
    except Exception:
        return False


# ── Helpers ────────────────────────────────────────────────────────

def _norm_market(market: str) -> str:
    return normalize_market_scope(market)


def _side_from_market(market: str) -> str:
    m = _norm_market(market)
    return "sh" if m.startswith("sh") else "sz" if m.startswith("sz") else m


def _side_from_filename(path: Path, market: str) -> str:
    name = path.name.lower()
    if name.startswith("sh"):
        return "sh"
    if name.startswith("sz"):
        return "sz"
    return _side_from_market(market)


def code_from_filename(path: Path, market: str) -> str:
    name = path.stem.lower()
    digits = "".join(c for c in name if c.isdigit())
    if len(digits) < 6:
        raise ValueError(f"Cannot parse stock code from file name: {path.name}")
    side = _side_from_filename(path, market)
    return f"{side}.{digits[-6:]}"


def _file_match(path: Path, market: str) -> bool:
    name = path.name.lower()
    return any(name.startswith(prefix) for prefix in market_file_prefixes(market))


def _date_str(v) -> str:
    return pd.to_datetime(v).strftime("%Y-%m-%d")


def _datetime_str(v) -> str:
    return pd.to_datetime(v).strftime("%Y-%m-%d %H:%M:%S")


def _start_day_s(start: Optional[str]) -> Optional[str]:
    return pd.to_datetime(start).strftime("%Y-%m-%d") if start else None


def _end_day_s(end: Optional[str]) -> Optional[str]:
    return pd.to_datetime(end).strftime("%Y-%m-%d") if end else None


def _start_min_s(start: Optional[str]) -> Optional[str]:
    return pd.to_datetime(start).strftime("%Y-%m-%d 00:00:00") if start else None


def _end_min_s(end: Optional[str]) -> Optional[str]:
    return pd.to_datetime(end).strftime("%Y-%m-%d 23:59:59") if end else None


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
    m = _norm_market(market)
    if m in ("sh60", "sh68", "sh"):
        sides = ("sh",)
    elif m in ("sz00", "sz30", "sz"):
        sides = ("sz",)
    else:
        sides = ("sh", "sz")
    t = (import_type or "all").lower()
    dirs: list[Path] = []
    for side in sides:
        base = root / side
        if t in ("all", "lday", "daily"):
            dirs.append(base / "lday")
        if t in ("all", "5m", "lc5", "fzline"):
            dirs.append(base / "fzline")
    return [d for d in dirs if d.exists() and d.is_dir()]


def _filter_rows_by_date(rows: list[dict], start: Optional[str], end: Optional[str], date_key: str = "date") -> list[dict]:
    if not start and not end:
        return rows
    result = []
    for r in rows:
        v = r[date_key]
        if start and v < start:
            continue
        if end and v > end:
            continue
        result.append(r)
    return result


# ── File readers ───────────────────────────────────────────────────

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
            "<IIIIIfII", content[offset:offset + record_size]
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


# ── Import functions ──────────────────────────────────────────────

def import_daily_clickhouse(path: str, market: str, start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """导入日线到 ClickHouse daily_kline 表。"""
    p = Path(path)
    try:
        code = code_from_filename(p, market)
        start_s = _start_day_s(start)
        end_s = _end_day_s(end)

        df = _read_daily(p)
        rows = []
        for _, row in df.iterrows():
            d = _date_str(row.get("date") if "date" in row else row.iloc[0])
            rows.append({
                "code": code,
                "date": d,
                "open": float(row.get("open", 0) or 0),
                "high": float(row.get("high", 0) or 0),
                "low": float(row.get("low", 0) or 0),
                "close": float(row.get("close", 0) or 0),
                "volume": float(_volume(row)),
                "amount": float(_amount(row)),
                "source": SOURCE,
            })
        rows = _filter_rows_by_date(rows, start_s, end_s, "date")

        inserted = ch_insert("daily_kline", rows)
        return {"ok": True, "file": str(p), "code": code, "rows": inserted, "type": "lday"}

    except Exception as exc:
        return {"ok": False, "file": str(p), "code": code if "code" in dir() else "<unknown>",
                "rows": 0, "type": "lday", "error": str(exc)}


def import_5m_clickhouse(path: str, market: str, start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """导入5分钟线到 ClickHouse minute_kline_period 表。"""
    p = Path(path)
    try:
        code = code_from_filename(p, market)
        start_s = _start_min_s(start)
        end_s = _end_min_s(end)

        df = _read_lc5(p)
        rows = []
        for _, row in df.iterrows():
            dt_col = row.get("date") if "date" in row else row.iloc[0]
            d = _datetime_str(dt_col)
            rows.append({
                "code": code,
                "date": d,
                "period": "5m",
                "open": float(row.get("open", 0) or 0),
                "high": float(row.get("high", 0) or 0),
                "low": float(row.get("low", 0) or 0),
                "close": float(row.get("close", 0) or 0),
                "volume": float(_volume(row)),
                "amount": float(_amount(row)),
                "source": SOURCE,
            })
        rows = _filter_rows_by_date(rows, start_s, end_s, "date")

        inserted = ch_insert("minute_kline_period", rows)
        return {"ok": True, "file": str(p), "code": code, "rows": inserted, "type": "5m"}

    except Exception as exc:
        return {"ok": False, "file": str(p), "code": code if "code" in dir() else "<unknown>",
                "rows": 0, "type": "5m", "error": str(exc)}


# ── Scan (compatible with existing API) ───────────────────────────

def scan_vipdoc_files(source_dir: str, market: str = "sh", import_type: str = "all") -> dict:
    """扫描文件（不读数据库，纯文件系统操作）。"""
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

    # Scan date range from .day files
    data_start = None
    data_end = None
    for p in files:
        if p.suffix.lower() == ".day":
            start, end = _day_file_edge_dates(p)
            if start:
                data_start = min(data_start, start) if data_start else start
            if end:
                data_end = max(data_end, end) if data_end else end

    return {
        "source_dir": str(root),
        "market": market,
        "import_type": import_type,
        "scan_dirs": [str(x) for x in scan_dirs],
        "total_files": len(files),
        "files": [str(x) for x in files],
        "file_data_start": data_start,
        "file_data_end": data_end,
        "file_data_range": f"{data_start} - {data_end}" if data_start and data_end else None,
    }


def _day_file_edge_dates(path: Path) -> tuple[int | None, int | None]:
    record_size = 32
    size = path.stat().st_size
    if size < record_size:
        return None, None
    with path.open("rb") as f:
        first = f.read(record_size)
        f.seek(size - record_size)
        last = f.read(record_size)
    return struct.unpack("<I", first[:4])[0], struct.unpack("<I", last[:4])[0]


# ── Main entry point ──────────────────────────────────────────────

def run_import(source_dir: str, market: str, import_type: str = "all",
               start: Optional[str] = None, end: Optional[str] = None,
               workers: int = 4, dry_run: bool = False):
    """主入口：扫描 + 导入到 ClickHouse。"""

    print(f"ClickHouse: {CH_URL} database={CH_DATABASE}")
    print(f"Ping: {'OK' if ch_ping() else 'FAIL'}")

    scan = scan_vipdoc_files(source_dir, market, import_type)
    print(f"Market: {market}, Files: {scan['total_files']}")
    print(f"Data range: {scan.get('file_data_range', 'N/A')}")

    if dry_run:
        print("DRY RUN: no data will be written")
        return scan

    if not scan["files"]:
        print("No files to import.")
        return scan

    lday_files = [f for f in scan["files"] if f.endswith(".day")]
    lc5_files = [f for f in scan["files"] if f.endswith(".lc5")]

    t0 = time.time()
    total_rows = 0
    ok_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}

        for f in lday_files:
            fut = pool.submit(import_daily_clickhouse, f, market, start, end)
            futures[fut] = f

        for f in lc5_files:
            fut = pool.submit(import_5m_clickhouse, f, market, start, end)
            futures[fut] = f

        for i, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            if result["ok"]:
                total_rows += result["rows"]
                ok_count += 1
            else:
                fail_count += 1
                logger.error("FAILED: %s -> %s", result.get("file", "?"), result.get("error", ""))

            if i % 100 == 0 or i == len(futures):
                elapsed = time.time() - t0
                speed = i / elapsed if elapsed > 0 else 0
                print(f"  [{i}/{len(futures)}] ok={ok_count} fail={fail_count} rows={total_rows} speed={speed:.1f} files/s")

    elapsed = time.time() - t0
    print(f"\nDone: {ok_count} ok, {fail_count} failed, {total_rows} rows in {elapsed:.1f}s ({total_rows/elapsed:.0f} rows/s)")
    return {"ok": ok_count, "failed": fail_count, "rows": total_rows, "elapsed": elapsed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="VIPDOC -> ClickHouse import")
    parser.add_argument("--source-dir", default="/data/vipdoc")
    parser.add_argument("--market", default="sh60")
    parser.add_argument("--import-type", default="all", choices=["all", "lday", "daily", "5m", "lc5", "fzline"])
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_import(
        source_dir=args.source_dir,
        market=args.market,
        import_type=args.import_type,
        start=args.start,
        end=args.end,
        workers=args.workers,
        dry_run=args.dry_run,
    )
