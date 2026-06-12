from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_mysql_schema_contains_v122_support_tables_and_constraints():
    sql = _read("sql/recreate_tables.sql")

    for table in [
        "market_state_daily",
        "hot_topic_daily",
        "stock_topic_position_daily",
        "morning_confirm_daily",
        "external_data_cache",
        "external_call_budget",
        "external_call_log",
    ]:
        assert f"CREATE TABLE {table}" in sql or f"CREATE TABLE IF NOT EXISTS {table}" in sql

    assert "missing_reason" in sql
    assert "chk_skipped_code" in sql
    assert "morning_grade = 'skipped' AND code = '__skip__'" in sql
    assert "ttl_hours" in sql


def test_clickhouse_schema_contains_v122_indicator_and_auction_fields():
    sql = _read("sql/clickhouse_tables.sql")

    for field in [
        "kdj_k",
        "kdj_d",
        "kdj_j",
        "kdj_j_cross_up",
        "kdj_j_over_100",
        "macd_dif",
        "macd_dea",
        "macd_hist",
        "macd_hist_green_shrink",
        "macd_hist_red_extend",
        "ma25_slope_days",
        "ma25_angle_deg",
        "ma5_slope_dir",
        "recent_3d_pct",
        "recent_5d_pct",
    ]:
        assert field in sql

    assert "adjust_type" in sql
    assert "CREATE TABLE auction_volume" in sql or "CREATE TABLE IF NOT EXISTS auction_volume" in sql
    assert "avg5_auction_volume Float64" in sql
