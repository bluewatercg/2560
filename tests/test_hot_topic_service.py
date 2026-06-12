import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/hot_topic_service.py"
SPEC = importlib.util.spec_from_file_location("hot_topic_service", MODULE_PATH)
hot_topic_service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hot_topic_service)

classify_hot_topic_strength = hot_topic_service.classify_hot_topic_strength
hot_topic_snapshot = hot_topic_service.hot_topic_snapshot
position_in_hot_topic = hot_topic_service.position_in_hot_topic


def test_classify_hot_topic_strength_marks_none_when_topic_is_missing_or_unranked():
    assert classify_hot_topic_strength(topic_pct_rank=None, limit_up_count=9) == "none"
    assert classify_hot_topic_strength(topic_pct_rank=0, limit_up_count=9) == "none"


def test_classify_hot_topic_strength_marks_strong_for_top_five_percent_with_enough_limit_ups():
    assert classify_hot_topic_strength(topic_pct_rank=5, limit_up_count=5) == "strong"
    assert classify_hot_topic_strength(topic_pct_rank=5, limit_up_count=4) == "medium"


def test_classify_hot_topic_strength_marks_medium_for_top_fifteen_percent_with_two_limit_ups():
    assert classify_hot_topic_strength(topic_pct_rank=15, limit_up_count=2) == "medium"
    assert classify_hot_topic_strength(topic_pct_rank=15.1, limit_up_count=10) == "weak"


def test_classify_hot_topic_strength_marks_weak_for_ranked_topic_that_is_not_strong_or_medium():
    assert classify_hot_topic_strength(topic_pct_rank=30, limit_up_count=1) == "weak"
    assert classify_hot_topic_strength(topic_pct_rank=80, limit_up_count=0) == "weak"


def test_position_in_hot_topic_prefers_explicit_leader_flag():
    assert position_in_hot_topic(is_leader=True, rank_pct=0.9) == "leader"


def test_position_in_hot_topic_marks_strong_for_top_twenty_percent_non_leader():
    assert position_in_hot_topic(is_leader=False, rank_pct=0.2) == "strong"


def test_position_in_hot_topic_marks_follower_for_middle_topic_members():
    assert position_in_hot_topic(is_leader=False, rank_pct=0.21) == "follower"
    assert position_in_hot_topic(is_leader=False, rank_pct=0.7) == "follower"


def test_position_in_hot_topic_marks_edge_for_missing_or_tail_rank():
    assert position_in_hot_topic(is_leader=False, rank_pct=None) == "edge"
    assert position_in_hot_topic(is_leader=False, rank_pct=0.71) == "edge"


def test_hot_topic_snapshot_returns_strength_position_and_inputs():
    result = hot_topic_snapshot(
        topic_pct_rank=4,
        limit_up_count=6,
        is_leader=False,
        rank_pct=0.18,
    )

    assert result == {
        "hot_topic_strength": "strong",
        "position_in_hot_topic": "strong",
        "topic_pct_rank": 4,
        "topic_limit_up_count": 6,
        "rank_pct": 0.18,
        "is_leader": False,
    }
