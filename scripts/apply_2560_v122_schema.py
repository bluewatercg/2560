#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pymysql


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def mysql_conn():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "192.168.1.254"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "watchlist_decision_support"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "watchlist_decision_support"),
        charset="utf8mb4",
        autocommit=False,
    )


def mysql_table_exists(cur, table: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = %s
        """,
        (table,),
    )
    return bool(cur.fetchone()[0])


def mysql_column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    )
    return bool(cur.fetchone()[0])


def mysql_constraint_exists(cur, table: str, constraint: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.table_constraints
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND constraint_name = %s
        """,
        (table, constraint),
    )
    return bool(cur.fetchone()[0])


def mysql_check_clause(cur, constraint: str) -> str | None:
    cur.execute(
        """
        SELECT CHECK_CLAUSE
        FROM information_schema.check_constraints
        WHERE constraint_schema = DATABASE()
          AND constraint_name = %s
        """,
        (constraint,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def mysql_check_has_non_null_morning_grade(clause: str | None) -> bool:
    if clause is None:
        return False
    normalized = " ".join(clause.replace("`", "").replace("(", " ").replace(")", " ").lower().split())
    return "morning_grade is not null" in normalized


def drop_mysql_check_if_exists(cur, table: str, constraint: str, applied: list[str]) -> None:
    if not mysql_constraint_exists(cur, table, constraint):
        return
    cur.execute(f"ALTER TABLE {table} DROP CHECK {constraint}")
    applied.append(f"MySQL DROP {constraint}")


def add_mysql_column(cur, table: str, column: str, ddl: str, applied: list[str]) -> None:
    if mysql_column_exists(cur, table, column):
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    applied.append(f"MySQL ADD {table}.{column}")


def add_mysql_columns(cur, table: str, columns: dict[str, str], applied: list[str]) -> None:
    for column, ddl in columns.items():
        add_mysql_column(cur, table, column, ddl, applied)


def create_mysql_tables(cur, applied: list[str]) -> None:
    table_sql = {
        "market_state_daily": """
            CREATE TABLE IF NOT EXISTS market_state_daily (
              trade_date DATE NOT NULL,
              index_code VARCHAR(20) NOT NULL,
              index_close DECIMAL(10,2),
              index_pct DECIMAL(6,3),
              limit_up_count INT,
              limit_down_count INT,
              up_count INT,
              down_count INT,
              up_ratio DECIMAL(5,4),
              market_state VARCHAR(20),
              environment_score DECIMAL(5,4),
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (trade_date, index_code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        "hot_topic_daily": """
            CREATE TABLE IF NOT EXISTS hot_topic_daily (
              trade_date DATE NOT NULL,
              topic_code VARCHAR(50) NOT NULL,
              topic_name VARCHAR(100),
              topic_pct DECIMAL(6,3),
              topic_pct_rank INT,
              limit_up_count INT,
              consecutive_high INT,
              leader_code VARCHAR(20),
              leader_name VARCHAR(50),
              hot_topic_strength VARCHAR(20),
              topic_score DECIMAL(5,4),
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (trade_date, topic_code),
              INDEX idx_strength (trade_date, hot_topic_strength)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        "stock_topic_position_daily": """
            CREATE TABLE IF NOT EXISTS stock_topic_position_daily (
              trade_date DATE NOT NULL,
              code VARCHAR(20) NOT NULL,
              topic_code VARCHAR(50) NOT NULL,
              rank_in_topic INT,
              is_leader TINYINT,
              is_consecutive_limit_up TINYINT,
              consecutive_days INT,
              position_label VARCHAR(20),
              position_score DECIMAL(5,4),
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (trade_date, code, topic_code),
              INDEX idx_code (trade_date, code),
              INDEX idx_position (trade_date, position_label)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        "morning_confirm_daily": """
            CREATE TABLE IF NOT EXISTS morning_confirm_daily (
              trade_date DATE NOT NULL,
              code VARCHAR(20) NOT NULL,
              yesterday_status VARCHAR(20),
              yesterday_final_score DECIMAL(5,4),
              yesterday_hot_topic VARCHAR(100),
              today_auction_volume BIGINT,
              yesterday_auction_volume BIGINT,
              avg5_auction_volume DOUBLE,
              auction_amplify_ratio DECIMAL(8,4),
              is_significantly_amplified TINYINT,
              open_gap_pct DECIMAL(6,3),
              pre_market_state VARCHAR(20),
              morning_grade VARCHAR(20),
              morning_score DECIMAL(5,4),
              missing_reason VARCHAR(100),
              confirm_time DATETIME DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (trade_date, code),
              INDEX idx_grade (trade_date, morning_grade)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        "external_data_cache": """
            CREATE TABLE IF NOT EXISTS external_data_cache (
              cache_key VARCHAR(120) NOT NULL PRIMARY KEY,
              source VARCHAR(50),
              data_json JSON,
              cache_date DATE,
              ttl_hours INT DEFAULT 24 COMMENT 'NULL=仅审计; 0=立即过期; >0=正常TTL',
              expire_at DATETIME,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_expire (expire_at),
              INDEX idx_source (source, cache_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        "external_call_budget": """
            CREATE TABLE IF NOT EXISTS external_call_budget (
              source VARCHAR(50) NOT NULL PRIMARY KEY,
              daily_limit INT,
              today_used INT DEFAULT 0,
              reset_at DATE,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        "external_call_log": """
            CREATE TABLE IF NOT EXISTS external_call_log (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              call_time DATETIME,
              source VARCHAR(50),
              endpoint VARCHAR(100),
              params JSON,
              status VARCHAR(20),
              duration_ms INT,
              response_size INT,
              error_msg TEXT,
              INDEX idx_time (call_time),
              INDEX idx_source (source, call_time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    }
    for table, sql in table_sql.items():
        existed = mysql_table_exists(cur, table)
        cur.execute(sql)
        if not existed:
            applied.append(f"MySQL CREATE {table}")


def migrate_mysql() -> list[str]:
    applied: list[str] = []
    conn = mysql_conn()
    try:
        with conn.cursor() as cur:
            create_mysql_tables(cur, applied)
            canonical_columns = {
                "selection_status": "VARCHAR(20) NULL",
                "final_score": "DECIMAL(5,4) NULL",
                "recent_3d_pct": "DECIMAL(6,3) NULL",
                "explode_status": "VARCHAR(20) NULL",
                "market_state": "VARCHAR(20) NULL",
                "environment_score": "DECIMAL(5,4) NULL",
                "hot_topic_strength": "VARCHAR(20) NULL",
                "position_in_hot_topic": "VARCHAR(20) NULL",
                "hot_topic_score": "DECIMAL(5,4) NULL",
                "volume_score": "DECIMAL(5,4) NULL",
                "structure_score": "DECIMAL(5,4) NULL",
                "intraday_score": "DECIMAL(5,4) NULL",
                "pressure_score": "DECIMAL(5,4) NULL",
            }
            for column, ddl in canonical_columns.items():
                add_mysql_column(cur, "structure_2560_analysis", column, ddl, applied)

            add_mysql_columns(
                cur,
                "market_state_daily",
                {
                    "index_close": "DECIMAL(10,2) NULL",
                    "index_pct": "DECIMAL(6,3) NULL",
                    "limit_up_count": "INT NULL",
                    "limit_down_count": "INT NULL",
                    "up_count": "INT NULL",
                    "down_count": "INT NULL",
                    "up_ratio": "DECIMAL(5,4) NULL",
                    "market_state": "VARCHAR(20) NULL",
                    "environment_score": "DECIMAL(5,4) NULL",
                    "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
                },
                applied,
            )
            add_mysql_columns(
                cur,
                "hot_topic_daily",
                {
                    "topic_name": "VARCHAR(100) NULL",
                    "topic_pct": "DECIMAL(6,3) NULL",
                    "topic_pct_rank": "INT NULL",
                    "limit_up_count": "INT NULL",
                    "consecutive_high": "INT NULL",
                    "leader_code": "VARCHAR(20) NULL",
                    "leader_name": "VARCHAR(50) NULL",
                    "hot_topic_strength": "VARCHAR(20) NULL",
                    "topic_score": "DECIMAL(5,4) NULL",
                    "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
                },
                applied,
            )
            add_mysql_columns(
                cur,
                "stock_topic_position_daily",
                {
                    "rank_in_topic": "INT NULL",
                    "is_leader": "TINYINT NULL",
                    "is_consecutive_limit_up": "TINYINT NULL",
                    "consecutive_days": "INT NULL",
                    "position_label": "VARCHAR(20) NULL",
                    "position_score": "DECIMAL(5,4) NULL",
                    "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
                },
                applied,
            )
            add_mysql_columns(
                cur,
                "morning_confirm_daily",
                {
                    "yesterday_status": "VARCHAR(20) NULL",
                    "yesterday_final_score": "DECIMAL(5,4) NULL",
                    "yesterday_hot_topic": "VARCHAR(100) NULL",
                    "today_auction_volume": "BIGINT NULL",
                    "yesterday_auction_volume": "BIGINT NULL",
                    "avg5_auction_volume": "DOUBLE NULL",
                    "auction_amplify_ratio": "DECIMAL(8,4) NULL",
                    "is_significantly_amplified": "TINYINT NULL",
                    "open_gap_pct": "DECIMAL(6,3) NULL",
                    "pre_market_state": "VARCHAR(20) NULL",
                    "morning_grade": "VARCHAR(20) NULL",
                    "morning_score": "DECIMAL(5,4) NULL",
                    "missing_reason": "VARCHAR(100) NULL",
                    "confirm_time": "DATETIME DEFAULT CURRENT_TIMESTAMP",
                },
                applied,
            )
            add_mysql_columns(
                cur,
                "external_data_cache",
                {
                    "source": "VARCHAR(50) NULL",
                    "data_json": "JSON NULL",
                    "cache_date": "DATE NULL",
                    "ttl_hours": "INT DEFAULT 24 COMMENT 'NULL=仅审计; 0=立即过期; >0=正常TTL'",
                    "expire_at": "DATETIME NULL",
                    "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
                },
                applied,
            )
            add_mysql_columns(
                cur,
                "external_call_budget",
                {
                    "daily_limit": "INT NULL",
                    "today_used": "INT DEFAULT 0",
                    "reset_at": "DATE NULL",
                    "updated_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
                },
                applied,
            )
            add_mysql_columns(
                cur,
                "external_call_log",
                {
                    "call_time": "DATETIME NULL",
                    "source": "VARCHAR(50) NULL",
                    "endpoint": "VARCHAR(100) NULL",
                    "params": "JSON NULL",
                    "status": "VARCHAR(20) NULL",
                    "duration_ms": "INT NULL",
                    "response_size": "INT NULL",
                    "error_msg": "TEXT NULL",
                },
                applied,
            )

            check_clause = mysql_check_clause(cur, "chk_skipped_code")
            if not mysql_check_has_non_null_morning_grade(check_clause):
                cur.execute(
                    """
                    UPDATE morning_confirm_daily
                    SET morning_grade = 'skipped'
                    WHERE code = '__skip__'
                      AND (morning_grade IS NULL OR morning_grade != 'skipped')
                    """
                )
                cur.execute(
                    """
                    UPDATE morning_confirm_daily
                    SET morning_grade = 'hold'
                    WHERE code != '__skip__'
                      AND (morning_grade IS NULL OR morning_grade = 'skipped')
                    """
                )
                drop_mysql_check_if_exists(cur, "morning_confirm_daily", "chk_skipped_code", applied)
                cur.execute(
                    """
                    ALTER TABLE morning_confirm_daily
                    ADD CONSTRAINT chk_skipped_code CHECK (
                      morning_grade IS NOT NULL
                      AND (
                        (morning_grade = 'skipped' AND code = '__skip__')
                        OR
                        (morning_grade != 'skipped' AND code != '__skip__')
                      )
                    )
                    """
                )
                applied.append("MySQL ADD chk_skipped_code")

            configs = [
                ("ma_price_period", "盘后均线参数", "25", "int", "关键均线周期"),
                ("vol_short_period", "盘后量能参数", "5", "int", "短期均量周期"),
                ("vol_long_period", "盘后量能参数", "60", "int", "长期均量周期"),
                ("atr_period", "盘后ATR参数", "14", "int", "ATR计算周期"),
                ("atr_compare_period", "盘后ATR参数", "20", "int", "ATR对比周期"),
                ("breakout_period", "盘后突破参数", "20", "int", "突破计算周期"),
                ("core_pullback_pct", "盘后回踩参数", "3.0", "double", "核心回踩百分比"),
                ("pullback_max_pct", "盘后回踩参数", "5.0", "double", "价格距离关键均线最大百分比"),
                ("recent_3d_normal_max", "盘后起爆段参数", "12.0", "double", "近3日普通状态最大涨幅"),
                ("recent_3d_warm_max", "盘后起爆段参数", "18.0", "double", "近3日温热状态最大涨幅"),
                ("recent_3d_acceleration_max", "盘后起爆段参数", "20.0", "double", "近3日加速状态最大涨幅"),
                ("recent_3d_overheat_min", "盘后起爆段参数", "20.0", "double", "近3日过热状态最小涨幅"),
                ("high_window_30m", "盘后30m参数", "20", "int", "30m压力位窗口"),
                ("confirm_5m_bars", "盘后5m参数", "6", "int", "5m确认K线数量"),
                ("volume_cross_fallback_enabled", "盘后量能参数", "true", "bool", "启用量能金叉回退确认"),
                ("volume_cross_confirm_ratio", "盘后量能参数", "0.9", "double", "量能金叉确认比例"),
                ("market_state_enabled", "盘后市场状态参数", "true", "bool", "启用市场状态过滤"),
                ("rebound_index_pct_min", "盘后市场状态参数", "0.5", "double", "反弹环境指数涨幅下限"),
                ("rebound_limitup_min", "盘后市场状态参数", "30", "int", "反弹环境涨停家数下限"),
                ("rebound_up_ratio_min", "盘后市场状态参数", "0.6", "double", "反弹环境上涨比例下限"),
                ("hot_topic_required", "盘后热点参数", "true", "bool", "要求热点题材匹配"),
                ("hot_topic_strength_required", "盘后热点参数", "medium", "string", "要求热点强度下限"),
                ("position_required_for_focus", "盘后热点参数", "strong", "string", "focus要求题材地位下限"),
                ("auction_amplify_ratio", "早盘竞价参数", "1.0", "double", "集合竞价放量确认比例"),
                ("auction_gap_pct_max", "早盘竞价参数", "3.0", "double", "集合竞价高开谨慎阈值"),
                ("auction_fallback_to_avg5", "早盘竞价参数", "true", "bool", "昨日竞价缺失时允许使用avg5兜底"),
                ("avg5_min_valid_days", "早盘竞价参数", "3", "int", "avg5竞价量最少有效天数"),
                ("display_emoji_enabled", "盘后展示参数", "false", "bool", "启用emoji展示"),
            ]
            for key, group, value, value_type, desc in configs:
                cur.execute(
                    """
                    INSERT INTO strategy_config
                    (strategy_code, config_key, config_group, config_value, value_type, description, enabled, updated_at)
                    VALUES ('S2560', %s, %s, %s, %s, %s, 1, NOW())
                    ON DUPLICATE KEY UPDATE
                      config_group=VALUES(config_group),
                      value_type=VALUES(value_type),
                      description=VALUES(description),
                      enabled=VALUES(enabled),
                      updated_at=NOW()
                    """,
                    (key, group, value, value_type, desc),
                )
            applied.append("MySQL UPSERT strategy_config v1.2.2 keys")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return applied


def ch_params(query: str) -> dict[str, str]:
    params = {
        "query": query,
        "database": os.getenv("CLICKHOUSE_DATABASE", "strategy2560"),
        "user": os.getenv("CLICKHOUSE_USER", "default"),
    }
    password = os.getenv("CLICKHOUSE_PASSWORD", "")
    if password:
        params["password"] = password
    return params


def ch_command(query: str) -> None:
    url = f"http://{os.getenv('CLICKHOUSE_HOST', '192.168.1.30')}:{os.getenv('CLICKHOUSE_PORT', '8123')}"
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, params=ch_params(query))
        if resp.status_code >= 400:
            raise RuntimeError(f"ClickHouse HTTP {resp.status_code}: {resp.text[:500]}")


def migrate_clickhouse() -> list[str]:
    applied: list[str] = []
    commands = [
        "ALTER TABLE daily_kline ADD COLUMN IF NOT EXISTS adjust_type LowCardinality(String) DEFAULT 'qfq'",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS kdj_k Nullable(Float64)",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS kdj_d Nullable(Float64)",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS kdj_j Nullable(Float64)",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS kdj_j_cross_up UInt8 DEFAULT 0",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS kdj_j_over_100 UInt8 DEFAULT 0",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS macd_dif Nullable(Float64)",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS macd_dea Nullable(Float64)",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS macd_hist Nullable(Float64)",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS macd_hist_green_shrink UInt8 DEFAULT 0",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS macd_hist_red_extend UInt8 DEFAULT 0",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS ma25_slope_days UInt16 DEFAULT 0",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS ma25_angle_deg Nullable(Float64)",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS ma5_slope_dir Int8 DEFAULT 0",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS recent_3d_pct Nullable(Float64)",
        "ALTER TABLE technical_indicator ADD COLUMN IF NOT EXISTS recent_5d_pct Nullable(Float64)",
        """
        CREATE TABLE IF NOT EXISTS auction_volume (
            code String,
            trade_date Date,
            auction_volume UInt64,
            auction_amount Float64,
            auction_open_price Float64,
            prev_close Float64,
            open_gap_pct Float64,
            yesterday_auction_volume UInt64,
            avg5_auction_volume Float64,
            auction_amplify_ratio Float64,
            is_significantly_amplified UInt8 DEFAULT 0,
            created_at DateTime64(3) DEFAULT now64(3)
        ) ENGINE = MergeTree()
        ORDER BY (code, trade_date)
        """,
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS auction_volume UInt64",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS auction_amount Float64",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS auction_open_price Float64",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS prev_close Float64",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS open_gap_pct Float64",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS yesterday_auction_volume UInt64",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS avg5_auction_volume Float64",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS auction_amplify_ratio Float64",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS is_significantly_amplified UInt8 DEFAULT 0",
        "ALTER TABLE auction_volume ADD COLUMN IF NOT EXISTS created_at DateTime64(3) DEFAULT now64(3)",
    ]
    for command in commands:
        ch_command(command)
        applied.append("ClickHouse " + " ".join(command.split()[:6]))
    return applied


def main() -> None:
    load_env()
    print("Applying 2560 v1.2.2 schema migration...")
    mysql_applied = migrate_mysql()
    ch_applied = migrate_clickhouse()
    print(f"MySQL changes checked/applied: {len(mysql_applied)}")
    for item in mysql_applied:
        print(f"  - {item}")
    print(f"ClickHouse changes checked/applied: {len(ch_applied)}")
    for item in ch_applied:
        print(f"  - {item}")
    print("2560 v1.2.2 schema migration complete.")


if __name__ == "__main__":
    main()
