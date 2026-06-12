from pathlib import Path

from app.api import jobs, latest
from app.services.annotation_engine_2568 import AnnotationEngine2568
from app.core.market_scope import market_sql_where
from scripts import build_30m_from_5m, progress_run_now, rebuild_technical_indicator, run_2560_analysis
from scripts.import_vipdoc_with_pytdx import _file_match, code_from_filename


def test_market_scope_sql_limits_broad_aliases_to_four_stock_boards():
    assert market_sql_where("code", "sh") == "(code LIKE 'sh.60%' OR code LIKE 'sh.68%')"
    assert market_sql_where("code", "sz") == "(code LIKE 'sz.00%' OR code LIKE 'sz.30%')"
    assert market_sql_where("code", "all") == (
        "(code LIKE 'sh.60%' OR code LIKE 'sh.68%' OR code LIKE 'sz.00%' OR code LIKE 'sz.30%')"
    )
    assert market_sql_where("code", " sh60 ") == "code LIKE 'sh.60%'"


def test_market_scope_helpers_share_the_same_restricted_sql():
    expected_sh = "(code LIKE 'sh.60%' OR code LIKE 'sh.68%')"
    assert build_30m_from_5m.code_where("sh") == expected_sh
    assert rebuild_technical_indicator.market_where("sh") == expected_sh
    assert run_2560_analysis.market_where("sh") == expected_sh
    assert progress_run_now.market_where("s", "sh") == expected_sh.replace("code", "s.code")
    assert jobs._market_where("s", "sz") == "(s.code LIKE 'sz.00%' OR s.code LIKE 'sz.30%')"
    assert latest._market_where("all") == (
        "(s.code LIKE 'sh.60%' OR s.code LIKE 'sh.68%' OR s.code LIKE 'sz.00%' OR s.code LIKE 'sz.30%')"
    )
    assert AnnotationEngine2568.market_where("s", "all") == latest._market_where("all")


def test_vipdoc_file_matching_excludes_non_target_security_types():
    assert _file_match(Path("sh600000.day"), "sh")
    assert _file_match(Path("sh688001.day"), "sh")
    assert not _file_match(Path("sh510300.day"), "sh")
    assert not _file_match(Path("sh900901.day"), "sh")

    assert _file_match(Path("sz000001.lc5"), "sz")
    assert _file_match(Path("sz300001.lc5"), "sz")
    assert not _file_match(Path("sz159915.lc5"), "sz")
    assert not _file_match(Path("sz399001.lc5"), "sz")


def test_index_scope_matches_only_supported_benchmark_indices():
    assert market_sql_where("code", "index") == (
        "(code LIKE 'sh.000001%' OR code LIKE 'sh.000300%' OR code LIKE 'sh.000688%' "
        "OR code LIKE 'sz.399001%' OR code LIKE 'sz.399006%')"
    )

    assert _file_match(Path("sh000001.day"), "index")
    assert _file_match(Path("sh000300.day"), "indices")
    assert _file_match(Path("sh000688.day"), "index")
    assert _file_match(Path("sz399001.lc5"), "index")
    assert _file_match(Path("sz399006.lc5"), "indices")

    assert not _file_match(Path("sh600000.day"), "index")
    assert not _file_match(Path("sz000001.lc5"), "index")


def test_code_from_filename_uses_filename_side_for_all_scope():
    assert code_from_filename(Path("sh600000.day"), "all") == "sh.600000"
    assert code_from_filename(Path("sz300001.lc5"), "all") == "sz.300001"
