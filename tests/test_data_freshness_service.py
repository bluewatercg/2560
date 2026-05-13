from app.services.data_freshness_service import classify_gap, can_run_2560


def test_classify_gap_reports_missing_when_db_lags_source():
    status, gap = classify_gap(source_latest=20260511, db_latest=20260506)
    assert status == "missing"
    assert gap == 5


def test_classify_gap_current_when_database_matches_source():
    status, gap = classify_gap(source_latest=20260511, db_latest=20260511)
    assert status == "current"
    assert gap == 0


def test_can_run_2560_requires_daily_5m_and_30m_to_reach_target():
    assert can_run_2560(20260511, 20260511, 20260511150000, 20260511150000) is True
    assert can_run_2560(20260511, 20260511, 20260506150000, 20260511150000) is False
    assert can_run_2560(20260511, 20260508, 20260511150000, 20260511150000) is False
