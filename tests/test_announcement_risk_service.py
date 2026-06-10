import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "announcement_risk_service_under_test",
        PROJECT_ROOT / "app/services/announcement_risk_service.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_announcement = _load_module()
CninfoAnnouncementRiskService = _announcement.CninfoAnnouncementRiskService
classify_latest_announcement = _announcement.classify_latest_announcement
parse_miaoxiang_search_news = _announcement.parse_miaoxiang_search_news


def test_classify_latest_announcement_marks_reduction_notice_as_bearish():
    result = classify_latest_announcement(
        "sz.002937",
        [
            {
                "announcementTitle": "关于公司控股股东、实际控制人及其一致行动人拟减持股份的预披露公告",
                "announcementTime": 1780502400000,
                "adjunctUrl": "finalpage/2026-06-03/test.PDF",
            }
        ],
    )

    assert result["announcement_risk_level"] == "high"
    assert result["announcement_sentiment"] == "利空"
    assert result["latest_announcement_summary"] == "最新公告：利空｜关于公司控股股东、实际控制人及其一致行动人拟减持股份的预披露公告"
    assert result["latest_announcement_items"][0]["sentiment_keywords"] == ["减持"]


def test_classify_latest_announcement_marks_buyback_as_bullish():
    result = classify_latest_announcement(
        "sh.603112",
        [
            {
                "announcementTitle": "关于控股股东提前终止减持计划暨未减持公司股份的公告",
                "announcementTime": 1780416000000,
            }
        ],
    )

    assert result["announcement_risk_level"] == "none"
    assert result["announcement_sentiment"] == "利好"
    assert result["latest_announcement_summary"] == "最新公告：利好｜关于控股股东提前终止减持计划暨未减持公司股份的公告"


def test_classify_latest_announcement_distinguishes_empty_result_from_fetch_error():
    result = classify_latest_announcement("sh.600000", [])

    assert result["announcement_risk_level"] == "none"
    assert result["announcement_sentiment"] == "无公告"
    assert result["latest_announcement_summary"] == "近期无公告"
    assert result["announcement_query_status"] == "ok"


def test_parse_miaoxiang_search_news_extracts_notice_for_fallback():
    payload = {
        "code": 200,
        "data": {
            "llmSearchResponse": {
                "data": [
                    {
                        "code": "AN202606031823213164",
                        "title": "精研科技:关于公司控股股东、实际控制人及其一致行动人、董事减持股份预披露公告",
                        "content": "拟减持数量占公司总股本比例不超过 1.27%",
                        "date": "2026-06-04 00:19:11",
                        "informationType": "NOTICE",
                        "jumpUrl": "https://pdf.dfcfw.com/pdf/H2_AN202606031823213164_1.PDF",
                    }
                ]
            }
        },
    }

    announcements = parse_miaoxiang_search_news(payload)
    result = classify_latest_announcement("sz.300709", announcements, source="miaoxiang")

    assert announcements[0]["announcementTitle"].startswith("精研科技:")
    assert announcements[0]["announcementUrl"].startswith("https://pdf.dfcfw.com")
    assert result["latest_announcement_source"] == "miaoxiang"
    assert result["announcement_sentiment"] == "利空"
    assert "减持" in result["latest_announcement_summary"]


def test_cninfo_fetch_error_is_sanitized_for_report_display():
    class BrokenCninfoAnnouncementRiskService(CninfoAnnouncementRiskService):
        def _query_cninfo(self, code: str, start_date: str, end_date: str):
            raise RuntimeError("Client error '403 Forbidden' for url 'http://www.cninfo.com.cn/new/hisAnnouncement/query'")

    result = BrokenCninfoAnnouncementRiskService().risk_for_code("sz.300852", "2026-06-01", "2026-06-04")

    assert result["announcement_risk_level"] == "unverified"
    assert result["announcement_sentiment"] == "未验证"
    assert result["latest_announcement_summary"] == "公告联网受限，暂未验证"
    assert result["announcement_query_status"] == "error"
    assert "403 Forbidden" in result["latest_announcement_error"]
    assert "cninfo.com.cn" not in result["latest_announcement_summary"]


def test_cninfo_error_falls_back_to_miaoxiang_notice():
    class FallbackCninfoAnnouncementRiskService(CninfoAnnouncementRiskService):
        def _query_cninfo(self, code: str, start_date: str, end_date: str):
            raise RuntimeError("403 Forbidden")

        def _query_miaoxiang(self, code: str, start_date: str, end_date: str):
            return [
                {
                    "announcementTitle": "精研科技:关于公司控股股东、实际控制人及其一致行动人、董事减持股份预披露公告",
                    "announcementTime": "2026-06-04 00:19:11",
                    "announcementUrl": "https://pdf.dfcfw.com/pdf/H2_AN202606031823213164_1.PDF",
                }
            ]

    result = FallbackCninfoAnnouncementRiskService(api_key="test-key").risk_for_code("sz.300709", "2026-06-01", "2026-06-05")

    assert result["announcement_query_status"] == "fallback"
    assert result["latest_announcement_source"] == "miaoxiang"
    assert result["announcement_sentiment"] == "利空"
    assert "减持" in result["latest_announcement_summary"]


def test_risks_for_codes_does_not_call_per_code_external_fetch_by_default(monkeypatch):
    monkeypatch.delenv("ANNOUNCEMENT_ALLOW_PER_CODE_CALLS", raising=False)

    class GuardedService(CninfoAnnouncementRiskService):
        def risk_for_code(self, code: str, start_date: str, end_date: str):
            raise AssertionError("per-code announcement call must stay disabled")

    result = GuardedService().risks_for_codes(["sh.600000", "sh.600000", "sz.000001"])

    assert list(result) == ["sh.600000", "sz.000001"]
    assert result["sh.600000"]["announcement_query_status"] == "error"
    assert result["sh.600000"]["announcement_risk_level"] == "unverified"
    assert "per-code announcement calls disabled" in result["sh.600000"]["latest_announcement_error"]
