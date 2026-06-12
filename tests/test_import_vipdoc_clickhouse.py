from scripts import import_vipdoc_clickhouse


def test_ch_replace_rows_deduplicates_daily_rows_by_code_and_date(monkeypatch):
    inserted_batches = []

    monkeypatch.setattr(import_vipdoc_clickhouse, "ch_command", lambda query: "")
    monkeypatch.setattr(
        import_vipdoc_clickhouse,
        "ch_insert",
        lambda table, rows, chunk_size=100_000: inserted_batches.append(rows.copy()) or len(rows),
    )

    inserted = import_vipdoc_clickhouse.ch_replace_rows(
        "daily_kline",
        [
            {"code": "sh.600000", "date": "2026-06-03", "close": 10.0, "source": "vipdoc"},
            {"code": "sh.600000", "date": "2026-06-03", "close": 11.0, "source": "vipdoc"},
        ],
    )

    assert inserted == 1
    assert inserted_batches[0] == [
        {"code": "sh.600000", "date": "2026-06-03", "close": 11.0, "source": "vipdoc"}
    ]


def test_ch_replace_rows_deduplicates_minute_rows_by_code_period_and_datetime(monkeypatch):
    inserted_batches = []

    monkeypatch.setattr(import_vipdoc_clickhouse, "ch_command", lambda query: "")
    monkeypatch.setattr(
        import_vipdoc_clickhouse,
        "ch_insert",
        lambda table, rows, chunk_size=100_000: inserted_batches.append(rows.copy()) or len(rows),
    )

    inserted = import_vipdoc_clickhouse.ch_replace_rows(
        "minute_kline_period",
        [
            {"code": "sh.600000", "period": "5m", "date": "2026-06-03 10:30:00", "close": 10.0},
            {"code": "sh.600000", "period": "5m", "date": "2026-06-03 10:30:00", "close": 11.0},
        ],
    )

    assert inserted == 1
    assert inserted_batches[0] == [
        {"code": "sh.600000", "period": "5m", "date": "2026-06-03 10:30:00", "close": 11.0}
    ]
