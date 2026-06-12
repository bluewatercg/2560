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
CH_HOST = os.getenv("CLICKHOUSE_HOST", "192.168.1.30")
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


def ch_insert(table: str, rows: list[dict], chunk_size: int = 100_000) -> int:
    """Batch insert via JSONEachRow format, chunked to avoid memory/timeout issues."""
    if not rows:
        return 0
    total = 0
    with httpx.Client(timeout=300) as client:
        for i in range(0, len(rows), chunk_size):
            batch = rows[i:i + chunk_size]
            body = "\n".join(json.dumps(row, default=str) for row in batch)
            query = f"INSERT INTO {CH_DATABASE}.{table} FORMAT JSONEachRow"
            params = {"database": CH_DATABASE, "user": CH_USER, "query": query}
            if CH_PASSWORD:
                params["password"] = CH_PASSWORD
            r = client.post(CH_URL, params=params, content=body.encode("utf-8"),
                           headers={"Content-Type": "application/x-ndjson"})
            r.raise_for_status()
            total += len(batch)
    return total


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _dedupe_rows_by_table_key(table: str, rows: list[dict]) -> list[dict]:
    if table == "daily_kline":
        key = lambda row: (row["code"], row["date"])
    elif table == "minute_kline_period":
        key = lambda row: (row["code"], row.get("period", "5m"), row["date"])
    else:
        raise ValueError(f"ch_replace_rows does not support table={table}")
    return list({key(row): row for row in rows}.values())


def ch_replace_rows(table: str, rows: list[dict], chunk_size: int = 100_000) -> int:
    """Idempotent ClickHouse write for kline rows.

    MergeTree does not enforce uniqueness. For each chunk, delete existing rows
    for the same table key scope, then insert de-duplicated rows.
    """
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), chunk_size):
        batch = rows[i:i + chunk_size]
        unique = _dedupe_rows_by_table_key(table, batch)
        codes = sorted({row["code"] for row in unique})
        dates = sorted({str(row["date"]) for row in unique})
        code_csv = ",".join(_quote(c) for c in codes)
        min_date, max_date = dates[0], dates[-1]
        if table == "daily_kline":
            delete_q = (
                f"ALTER TABLE {CH_DATABASE}.{table} DELETE "
                f"WHERE code IN ({code_csv}) "
                f"AND date >= toDate({_quote(min_date[:10])}) "
                f"AND date <= toDate({_quote(max_date[:10])}) "
                "SETTINGS mutations_sync=2"
            )
        elif table == "minute_kline_period":
            periods = sorted({row.get("period", "5m") for row in unique})
            period_csv = ",".join(_quote(p) for p in periods)
            delete_q = (
                f"ALTER TABLE {CH_DATABASE}.{table} DELETE "
                f"WHERE code IN ({code_csv}) "
                f"AND period IN ({period_csv}) "
                f"AND date >= toDateTime({_quote(min_date[:19])}) "
                f"AND date <= toDateTime({_quote(max_date[:19])}) "
                "SETTINGS mutations_sync=2"
            )
        else:
            raise ValueError(f"ch_replace_rows does not support table={table}")
        ch_command(delete_q)
        total += ch_insert(table, unique, chunk_size=chunk_size)
    return total


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


# ── Read-only functions (no ClickHouse write) ──────────────────────

def read_daily_rows(path: str, market: str, start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """读取日线文件，返回 rows 列表但不写 ClickHouse。"""
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
        return {"ok": True, "file": str(p), "code": code, "rows": rows, "type": "lday"}

    except Exception as exc:
        return {"ok": False, "file": str(p), "code": code if "code" in dir() else "<unknown>",
                "rows": [], "type": "lday", "error": str(exc)}


def read_5m_rows(path: str, market: str, start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """读取5分钟线文件，返回 rows 列表但不写 ClickHouse。"""
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
        return {"ok": True, "file": str(p), "code": code, "rows": rows, "type": "5m"}

    except Exception as exc:
        return {"ok": False, "file": str(p), "code": code if "code" in dir() else "<unknown>",
                "rows": [], "type": "5m", "error": str(exc)}


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

        inserted = ch_replace_rows("daily_kline", rows)
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

        inserted = ch_replace_rows("minute_kline_period", rows)
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
    """主入口：两阶段导入 — 先逐文件读到内存，再批量写 ClickHouse。"""

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

    if import_type in ("lday", "daily"):
        lc5_files = []
    elif import_type in ("5m", "lc5", "fzline"):
        lday_files = []

    all_files = lday_files + lc5_files
    total = len(all_files)
    t0 = time.time()

    flush_rows = int(os.getenv("IMPORT_FLUSH_ROWS", "100000"))
    daily_buffer: list[dict] = []
    minute_buffer: list[dict] = []
    ok_count = 0
    fail_count = 0
    total_rows = 0

    def flush_buffer(table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        inserted = ch_replace_rows(table, rows)
        rows.clear()
        return inserted

    print(f"Phase 1: reading {total} files sequentially, flush_rows={flush_rows}", flush=True)
    for i, f in enumerate(all_files, 1):
        if f.endswith(".day"):
            result = read_daily_rows(f, market, start, end)
        else:
            result = read_5m_rows(f, market, start, end)

        if result["ok"]:
            ok_count += 1
            rows = result.get("rows", [])
            if result.get("type") == "lday":
                daily_buffer.extend(rows)
                if len(daily_buffer) >= flush_rows:
                    total_rows += flush_buffer("daily_kline", daily_buffer)
            elif result.get("type") == "5m":
                minute_buffer.extend(rows)
                if len(minute_buffer) >= flush_rows:
                    total_rows += flush_buffer("minute_kline_period", minute_buffer)
        else:
            fail_count += 1
            logger.error("FAILED: %s -> %s", result.get("file", "?"), result.get("error", ""))

        if i % 100 == 0 or i == total:
            elapsed = time.time() - t0
            speed = i / elapsed if elapsed > 0 else 0
            print(f"  [{i}/{total}] ok={ok_count} fail={fail_count} inserted={total_rows} daily_buffer={len(daily_buffer)} minute_buffer={len(minute_buffer)} speed={speed:.1f} files/s")

    print(f"Phase 1 done: {ok_count} ok, {fail_count} failed, {len(daily_buffer)} daily buffered rows, {len(minute_buffer)} minute buffered rows", flush=True)

    try:
        if daily_buffer:
            t_ins = time.time()
            print(f"Phase 2: inserting {len(daily_buffer)} daily rows", flush=True)
            inserted = flush_buffer("daily_kline", daily_buffer)
            total_rows += inserted
            print(f"daily insert done: {inserted} rows in {time.time()-t_ins:.1f}s", flush=True)

        if minute_buffer:
            t_ins = time.time()
            print(f"Phase 2: inserting {len(minute_buffer)} minute rows", flush=True)
            inserted = flush_buffer("minute_kline_period", minute_buffer)
            total_rows += inserted
            print(f"minute insert done: {inserted} rows in {time.time()-t_ins:.1f}s", flush=True)
    except Exception as e:
        fail_count += 1
        print(f"Phase 2 INSERT failed: {e}", flush=True)

    elapsed = time.time() - t0
    print(f"\nDone: {ok_count} ok, {fail_count} failed in {elapsed:.1f}s", flush=True)
    return {"ok": ok_count if fail_count == 0 else False, "failed": fail_count, "rows": total_rows, "elapsed": elapsed}


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
