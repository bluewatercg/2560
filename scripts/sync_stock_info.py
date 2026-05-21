#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 mootdx 同步 A 股股票列表到 stock_info 表（本地工具，不在 Docker 容器内运行）。

覆盖 4 个市场：
- sh60: 上证主板 (60xxxx)
- sh68: 科创板 (68xxxx)
- sz00: 深市主板 (00xxxx)
- sz30: 创业板 (30xxxx)

用法：
    python scripts/sync_stock_info.py              # 全量同步
    python scripts/sync_stock_info.py --market sh60  # 仅同步某市场
    python scripts/sync_stock_info.py --dry-run      # 预览不写入
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

MARKET_PREFIXES = {
    "sh60": ("60",),
    "sh68": ("68",),
    "sz00": ("00",),
    "sz30": ("30",),
}

ALL_PREFIXES = tuple(v for vals in MARKET_PREFIXES.values() for v in vals)


def db_url() -> str:
    import os
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return (
        f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD', '')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT', '3306')}"
        f"/{os.getenv('DB_NAME')}?charset=utf8mb4"
    )


def code_prefix(raw_code: str) -> str:
    s = raw_code.strip()
    if len(s) >= 2:
        return s[:2]
    return ""


def to_full_code(raw_code: str) -> str:
    p = code_prefix(raw_code)
    if p in ("60", "68"):
        return f"sh.{raw_code}"
    if p in ("00", "30"):
        return f"sz.{raw_code}"
    return ""


def fetch_all_stocks_from_mootdx() -> list[dict]:
    """使用 mootdx 拉取全量 A 股列表"""
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std", timeout=15)
    all_stocks = client.stock_all()
    return all_stocks.to_dict("records")


def filter_our_stocks(mootdx_rows: list[dict]) -> list[dict]:
    """过滤出 sh60/sh68/sz00/sz30 市场"""
    rows = []
    for r in mootdx_rows:
        raw = str(r.get("code", "")).strip()
        if not raw.isdigit():
            continue
        p = code_prefix(raw)
        if p not in ALL_PREFIXES:
            continue
        full = to_full_code(raw)
        if not full:
            continue

        market = "sh60" if p == "60" else "sh68" if p == "68" else "sz00" if p == "00" else "sz30"
        name = str(r.get("name", "")).strip()
        if any(kw in name for kw in ["指数", "基金", "转债", "ETF", "LOF"]):
            continue
        if not name:
            continue

        rows.append({
            "code": full,
            "name": name,
            "market": market,
            "code_type": {"60": "sh60", "68": "sh68", "00": "sz00", "30": "sz30"}[p],
            "source": "mootdx",
        })
    return rows


def sync(dry_run: bool = False, markets: list[str] | None = None):
    print("[sync] fetching all stocks from mootdx ...")
    tdx_rows = fetch_all_stocks_from_mootdx()
    print(f"[sync] total from mootdx: {len(tdx_rows)}")

    rows = filter_our_stocks(tdx_rows)
    print(f"[sync] filtered to our 4 markets: {len(rows)}")

    if markets:
        rows = [r for r in rows if r["market"] in markets]
        print(f"[sync] after market filter ({','.join(markets)}): {len(rows)}")

    if dry_run:
        print("[sync] --dry-run, no DB write")
        for r in rows[:10]:
            print(f"  {r['code']}  {r['name']}  ({r['market']})")
        return

    en = create_engine(db_url(), pool_pre_ping=True)
    with en.begin() as conn:
        for r in rows:
            r["now"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not rows:
            print("[sync] no rows to sync")
            return

        conn.execute(
            text("""
                INSERT INTO stock_info
                    (code, name, market, code_type, source, updated_at)
                VALUES
                    (:code, :name, :market, :code_type, :source, :now)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    market = VALUES(market),
                    code_type = VALUES(code_type),
                    source = VALUES(source),
                    updated_at = VALUES(updated_at)
            """),
            rows,
        )

    # 从 ClickHouse 回填 record_count / last_date
    try:
        from app.db.clickhouse import get_clickhouse

        print("[sync] updating record_count from ClickHouse ...")
        ch = get_clickhouse()
        with en.begin() as conn:
            codes = [r["code"] for r in rows]
            batch_size = 500
            updated = 0
            for i in range(0, len(codes), batch_size):
                chunk = codes[i : i + batch_size]
                code_list = ", ".join(f"'{c}'" for c in chunk)
                ch_rows = ch.query(
                    f"SELECT code, count() as cnt, max(date) as last_date "
                    f"FROM daily_kline WHERE code IN ({code_list}) GROUP BY code"
                )
                if ch_rows:
                    for cr in ch_rows:
                        conn.execute(
                            text("""
                                UPDATE stock_info
                                SET record_count = :rc,
                                    last_date = :ld,
                                    updated_at = :now
                                WHERE code = :code
                            """),
                            {
                                "rc": int(cr.get("cnt", 0)),
                                "ld": int(str(cr["last_date"]).replace("-", "")[:8]),
                                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "code": cr["code"],
                            },
                        )
                        updated += 1
            print(f"[sync] updated record_count for {updated} stocks")
    except Exception as e:
        print(f"[sync] warning: failed to update record_count from ClickHouse: {e}")
        import traceback
        traceback.print_exc()

    print(f"[sync] done. {len(rows)} rows upserted to stock_info")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", action="append", choices=list(MARKET_PREFIXES.keys()),
                        help="只同步指定市场，可多次指定")
    parser.add_argument("--dry-run", action="store_true", help="预览不写入")
    args = parser.parse_args()
    sync(dry_run=args.dry_run, markets=args.market)


if __name__ == "__main__":
    main()
