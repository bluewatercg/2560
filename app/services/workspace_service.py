"""workspace_status 表管理。

每次数据操作完成后，按 market 写入"数据最新到 XXXX"的记录。
/workspace 端点只读这张小表，不做 MAX() 聚合。
"""
from __future__ import annotations
import json

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.clickhouse import get_clickhouse

_MARKETS = ["sh60", "sh68", "sz00", "sz30"]


def ensure_workspace_table(db: Session) -> bool:
    """确保 workspace_status 表存在并初始化四行。返回是否刚创建的。"""
    row = db.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = 'workspace_status'
    """)).scalar()
    if int(row or 0) == 0:
        db.execute(text("""
            CREATE TABLE workspace_status (
                market VARCHAR(10) PRIMARY KEY,
                daily_latest     INT DEFAULT NULL COMMENT '日线最新日期 YYYYMMDD',
                k5m_latest       BIGINT DEFAULT NULL COMMENT '5m K线最新日期 YYYYMMDDHHMMSS',
                k30m_latest      BIGINT DEFAULT NULL COMMENT '30m K线最新日期',
                ind_daily        INT DEFAULT NULL COMMENT '日线指标最新日期',
                ind_5m           BIGINT DEFAULT NULL COMMENT '5m 指标最新日期',
                ind_30m          BIGINT DEFAULT NULL COMMENT '30m 指标最新日期',
                source_daily     INT DEFAULT NULL COMMENT '源文件日线最新日期',
                indicators_fresh TINYINT(1) DEFAULT 0,
                ready            TINYINT(1) DEFAULT 0,
                missing_json     JSON DEFAULT NULL,
                status_text      VARCHAR(50) DEFAULT '',
                daily_gap_label  VARCHAR(20) DEFAULT '',
                daily_gap        INT DEFAULT NULL,
                updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        for m in _MARKETS:
            db.execute(text("INSERT IGNORE INTO workspace_status (market) VALUES (:m)"), {"m": m})
        db.commit()
        return True
    return False


def update_market_latest(
    db: Session,
    market: str,
    *,
    daily: int | None = None,
    k5m: int | None = None,
    k30m: int | None = None,
    ind_daily: int | None = None,
    ind_5m: int | None = None,
    ind_30m: int | None = None,
    source_daily: int | None = None,
    replace_fields: set[str] | None = None,
) -> None:
    """更新某个 market 的 workspace_status 行。

    只更新非 None 的列，未传入的列保持原值不变。
    replace_fields 中的字段即使为 None 也会写入（清空旧值）。
    同时重新计算 ready / indicators_fresh / status_text / missing。
    """
    ensure_workspace_table(db)
    replace_fields = replace_fields or set()

    # 先读当前行（保留未指定的列）
    cur = db.execute(text("""
        SELECT daily_latest, k5m_latest, k30m_latest,
               ind_daily, ind_5m, ind_30m, source_daily
        FROM workspace_status WHERE market = :m
    """), {"m": market}).mappings().first()

    if not cur:
        return

    d_daily = daily if (daily is not None or "daily" in replace_fields) else cur["daily_latest"]
    dk5m = k5m if (k5m is not None or "k5m" in replace_fields) else cur["k5m_latest"]
    dk30m = k30m if (k30m is not None or "k30m" in replace_fields) else cur["k30m_latest"]
    i_daily = ind_daily if (ind_daily is not None or "ind_daily" in replace_fields) else cur["ind_daily"]
    i5m = ind_5m if (ind_5m is not None or "ind_5m" in replace_fields) else cur["ind_5m"]
    i30m = ind_30m if (ind_30m is not None or "ind_30m" in replace_fields) else cur["ind_30m"]
    src_daily = source_daily if (source_daily is not None or "source_daily" in replace_fields) else cur["source_daily"]

    # 重新计算 indicators_fresh
    indicators_fresh = True
    if dk30m is not None:
        indicators_fresh = indicators_fresh and (i30m is not None and i30m >= dk30m // 1000000)
    if d_daily is not None:
        indicators_fresh = indicators_fresh and (i_daily is not None and i_daily >= d_daily)
    if dk5m is not None:
        indicators_fresh = indicators_fresh and (i5m is not None and i5m >= dk5m // 1000000)

    # ready = 有 daily+5m+30m 且指标已最新
    has_all = d_daily is not None and dk5m is not None and dk30m is not None
    ready = has_all and indicators_fresh

    # missing
    missing = []
    if d_daily is None:
        missing.append("daily")
    if dk5m is None:
        missing.append("5m")
    if dk30m is None:
        missing.append("30m")

    # status_text
    if missing:
        status_text = "数据不足"
    elif not indicators_fresh:
        status_text = "指标未更新"
    elif has_all:
        status_text = "可跑2560"
    else:
        status_text = "数据已最新，等待计算"

    # gap 计算（源文件 vs DB）
    from app.services.data_freshness_service import classify_gap
    daily_gap_label, daily_gap = classify_gap(src_daily, d_daily)

    db.execute(text("""
        UPDATE workspace_status SET
            daily_latest = :daily_latest,
            k5m_latest = :k5m_latest,
            k30m_latest = :k30m_latest,
            ind_daily = :ind_daily,
            ind_5m = :ind_5m,
            ind_30m = :ind_30m,
            source_daily = :source_daily,
            indicators_fresh = :indicators_fresh,
            ready = :ready,
            missing_json = :missing_json,
            status_text = :status_text,
            daily_gap_label = :daily_gap_label,
            daily_gap = :daily_gap
        WHERE market = :market
    """), {
        "market": market,
        "daily_latest": d_daily,
        "k5m_latest": dk5m,
        "k30m_latest": dk30m,
        "ind_daily": i_daily,
        "ind_5m": i5m,
        "ind_30m": i30m,
        "source_daily": src_daily,
        "indicators_fresh": int(indicators_fresh),
        "ready": int(ready),
        "missing_json": json.dumps(missing, ensure_ascii=False) if missing else None,
        "status_text": status_text,
        "daily_gap_label": daily_gap_label,
        "daily_gap": daily_gap,
    })
    db.commit()


def refresh_market_from_db(db: Session, market: str, *, periods: list[str] | None = None) -> None:
    """查询数据库实际最新日期并更新 workspace_status。

    periods 可指定需要刷新的周期，默认全部。
    用于操作完成后自动刷新，避免 runner 脚本传递错误日期。

    注意：daily_kline 和 minute_kline_period 从 ClickHouse 读取，
    technical_indicator 仍从 MySQL 读取。
    """
    ensure_workspace_table(db)
    from app.core.market_scope import market_sql_where

    sets: dict[str, int | None] = {}
    replace_fields: set[str] = set()

    if periods is None or "daily" in periods:
        where = market_sql_where("code", market)
        row = get_clickhouse().query_one(
            f"SELECT max(date) AS d FROM daily_kline WHERE {where}"
        )
        if row and row.get("d"):
            try:
                d = pd.to_datetime(row["d"])
                if d.year > 2100:
                    sets["daily"] = None
                else:
                    sets["daily"] = int(d.strftime("%Y%m%d"))
            except Exception:
                sets["daily"] = None
        else:
            sets["daily"] = None
        replace_fields.add("daily")
        sets["source_daily"] = sets["daily"]
        replace_fields.add("source_daily")

    if periods is None or "5m" in periods:
        where = market_sql_where("code", market)
        row = get_clickhouse().query_one(
            f"SELECT max(date) AS d FROM minute_kline_period WHERE period='5m' AND {where}"
        )
        if row and row.get("d"):
            try:
                d = pd.to_datetime(row["d"])
                if d.year > 2100:
                    sets["k5m"] = None
                else:
                    sets["k5m"] = int(d.strftime("%Y%m%d%H%M%S"))
            except Exception:
                sets["k5m"] = None
        else:
            sets["k5m"] = None
        replace_fields.add("k5m")

    if periods is None or "30m" in periods:
        where = market_sql_where("code", market)
        row = get_clickhouse().query_one(
            f"SELECT max(date) AS d FROM minute_kline_period WHERE period='30m' AND {where}"
        )
        if row and row.get("d"):
            try:
                d = pd.to_datetime(row["d"])
                if d.year > 2100:
                    sets["k30m"] = None
                else:
                    sets["k30m"] = int(d.strftime("%Y%m%d%H%M%S"))
            except Exception:
                sets["k30m"] = None
        else:
            sets["k30m"] = None
        replace_fields.add("k30m")

    # 指标 — 从 ClickHouse technical_indicator 读取（行情指标，不存 MySQL）
    if periods is None or "daily" in periods:
        row = get_clickhouse().query_one(
            f"SELECT max(date) AS d FROM technical_indicator WHERE period='daily' AND {market_sql_where('code', market)}"
        )
        if row and row.get("d"):
            try:
                d = pd.to_datetime(row["d"])
                if d.year > 2100:
                    sets["ind_daily"] = None
                else:
                    sets["ind_daily"] = int(d.strftime("%Y%m%d"))
            except Exception:
                sets["ind_daily"] = None
        else:
            sets["ind_daily"] = None
        replace_fields.add("ind_daily")

    if periods is None or "5m" in periods:
        row = get_clickhouse().query_one(
            f"SELECT max(date) AS d FROM technical_indicator WHERE period='5m' AND {market_sql_where('code', market)}"
        )
        if row and row.get("d"):
            try:
                d = pd.to_datetime(row["d"])
                if d.year > 2100:
                    sets["ind_5m"] = None
                else:
                    sets["ind_5m"] = int(d.strftime("%Y%m%d%H%M%S"))
            except Exception:
                sets["ind_5m"] = None
        else:
            sets["ind_5m"] = None
        replace_fields.add("ind_5m")

    if periods is None or "30m" in periods:
        row = get_clickhouse().query_one(
            f"SELECT max(date) AS d FROM technical_indicator WHERE period='30m' AND {market_sql_where('code', market)}"
        )
        if row and row.get("d"):
            try:
                d = pd.to_datetime(row["d"])
                if d.year > 2100:
                    sets["ind_30m"] = None
                else:
                    sets["ind_30m"] = int(d.strftime("%Y%m%d%H%M%S"))
            except Exception:
                sets["ind_30m"] = None
        else:
            sets["ind_30m"] = None
        replace_fields.add("ind_30m")

    update_market_latest(db, market, replace_fields=replace_fields, **sets)
