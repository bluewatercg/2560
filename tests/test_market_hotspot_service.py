import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "market_hotspot_service_under_test",
        PROJECT_ROOT / "app/services/market_hotspot_service.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_hotspot = _load_module()
DEFAULT_HOTSPOT_QUESTION = _hotspot.DEFAULT_HOTSPOT_QUESTION
EastmoneyHotspotDiscoveryService = _hotspot.EastmoneyHotspotDiscoveryService
build_hotspot_snapshot = _hotspot.build_hotspot_snapshot
match_candidate_to_hotspots = _hotspot.match_candidate_to_hotspots
parse_hotspot_display_data = _hotspot.parse_hotspot_display_data


def test_parse_hotspot_display_data_extracts_rank_code_and_theme():
    display_data = """
| 热度排名 | 股票名称 | 相关标签 | 相关热点 | 现价 | 涨跌幅 |
| --- | --- | --- | --- | --- | --- |
| 1 | 京东方Ａ(000725) | null | 玻璃基板或成下一代先进封装核心材料<br>随AI算力芯片向大尺寸、高集成演进。 | 6.15 | 10.02% |
| 2 | 亨通光电(600487) | null | 光纤光缆订单爆满，头部企业紧急扩产<br>受AI算力建设驱动。 | 97.87 | 7.04% |
"""

    items = parse_hotspot_display_data(display_data)

    assert items[0]["rank"] == 1
    assert items[0]["code"] == "sz.000725"
    assert items[0]["name"] == "京东方Ａ"
    assert items[0]["theme"] == "玻璃基板或成下一代先进封装核心材料"
    assert items[1]["code"] == "sh.600487"


def test_match_candidate_to_hotspots_marks_exact_code_as_strong_match():
    snapshot = {
        "hotspot_status": "available",
        "hotspot_items": [
            {
                "rank": 1,
                "code": "sz.000725",
                "name": "京东方Ａ",
                "theme": "玻璃基板或成下一代先进封装核心材料",
            }
        ],
    }

    result = match_candidate_to_hotspots({"code": "sz.000725", "name": "京东方Ａ"}, snapshot)

    assert result["hotspot_match_level"] == "强匹配"
    assert result["hotspot_theme"] == "玻璃基板或成下一代先进封装核心材料"
    assert result["hotspot_rank"] == 1
    assert result["hotspot_match_summary"] == "热点强匹配：玻璃基板或成下一代先进封装核心材料"


def test_parse_hotspot_display_data_extracts_industry_themes_from_news_table():
    display_data = """
| 热度排名 | 资讯标题 | 资讯内容 | 资讯时间 |
| --- | --- | --- | --- |
| 1 | A股三大指数收跌 创业板指跌超3% 机器人概念股逆市大涨 | 行业板块涨多跌少，机器人、航天装备、玻璃玻纤、金属新材料、非金属材料板块涨幅居前，电力、公用事业、核力发电、半导体板块跌幅居前。 | 2026-06-05 |
"""

    items = parse_hotspot_display_data(display_data)

    assert [x["theme"] for x in items[:5]] == ["机器人", "航天装备", "玻璃玻纤", "金属新材料", "非金属材料"]
    assert items[0]["related_hotspot"].startswith("A股三大指数收跌")


def test_build_snapshot_from_news_table_is_available_and_matches_candidate_industry():
    raw = {
        "code": 200,
        "status": 200,
        "data": {
            "displayData": """
| 热度排名 | 资讯标题 | 资讯内容 | 资讯时间 |
| --- | --- | --- | --- |
| 1 | 机器人概念股逆市大涨 | 行业板块涨多跌少，机器人、航天装备、玻璃玻纤板块涨幅居前。 | 2026-06-05 |
"""
        },
    }

    snapshot = build_hotspot_snapshot(raw)
    result = match_candidate_to_hotspots({"code": "sz.300000", "name": "样例", "industry_name": "机器人"}, snapshot)

    assert snapshot["hotspot_status"] == "available"
    assert snapshot["hotspot_summary"].startswith("机器人")
    assert result["hotspot_match_level"] == "弱匹配"
    assert result["hotspot_theme"] == "机器人"


def test_build_snapshot_falls_back_to_full_text_theme_extraction_when_table_parse_fails():
    raw = {
        "code": 200,
        "status": 200,
        "data": {
            "displayData": """
| 热度排名 | 资讯标题 | 资讯内容 | 资讯时间 |
| --- | --- | --- | --- |
| 1 | A股三大指数收跌 创业板指跌超3% 机器人概念股逆市大涨 | A股三大指数今日集体回调。行业板块涨多跌少，机器人、航天装备、玻璃玻纤、金属新材料、非金属材料板块涨幅居前，电力、公用事业、核力发电、半导体板块跌幅居前。个股方面，上涨股票数量接近3300只，逾80只股票涨停，机器人概念股表现活跃，绿的谐波20cm涨停，鼎智科技、三丰智能涨超10%。\\n\\n近期，上交所向券商下发通知
"""
        },
    }

    snapshot = build_hotspot_snapshot(raw)

    assert snapshot["hotspot_status"] == "available"
    assert snapshot["hotspot_summary"] == "机器人 / 航天装备 / 玻璃玻纤 / 金属新材料 / 非金属材料"


def test_hotspot_service_without_api_key_is_unverified_not_network_call():
    service = EastmoneyHotspotDiscoveryService(api_key="")

    snapshot = service.snapshot("今天A股市场热点是什么？")

    assert snapshot["hotspot_status"] == "unverified"
    assert snapshot["hotspot_summary"] == "热点主线未验证"
    assert snapshot["hotspot_items"] == []


def test_hotspot_service_retries_stable_question_when_custom_question_is_unsupported():
    class DummyHotspotService(EastmoneyHotspotDiscoveryService):
        def __init__(self):
            super().__init__(api_key="test")
            self.queries = []

        def _query(self, question):
            self.queries.append(question)
            if question != DEFAULT_HOTSPOT_QUESTION:
                return {"code": -1, "status": -1, "message": "该skill暂时不支持此类场景分析，请选择其他skill"}
            return {
                "code": 200,
                "status": 200,
                "message": "成功",
                "data": {
                    "displayData": """
| 热度排名 | 资讯标题 | 资讯内容 | 资讯时间 |
| --- | --- | --- | --- |
| 1 | 机器人概念股逆市大涨 | 行业板块涨多跌少，机器人、航天装备板块涨幅居前。 | 2026-06-05 |
"""
                },
            }

    service = DummyHotspotService()

    snapshot = service.snapshot("2026-06-04 A股市场热点主线是什么？请列出热点板块、代表股票和驱动原因。")

    assert service.queries == [
        "2026-06-04 A股市场热点主线是什么？请列出热点板块、代表股票和驱动原因。",
        DEFAULT_HOTSPOT_QUESTION,
    ]
    assert snapshot["hotspot_status"] == "available"
    assert snapshot["hotspot_summary"] == "机器人 / 航天装备"
