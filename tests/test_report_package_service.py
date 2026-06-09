from __future__ import annotations

import json
import importlib.util
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_report_package_module():
    saved = {name: sys.modules.get(name) for name in ["app", "app.services"]}
    app = types.ModuleType("app")
    app.__path__ = []
    services = types.ModuleType("app.services")
    services.__path__ = []
    sys.modules["app"] = app
    sys.modules["app.services"] = services
    try:
        spec = importlib.util.spec_from_file_location(
            "report_package_service_under_test",
            PROJECT_ROOT / "app/services/report_package_service.py",
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


ReportPackageService = _load_report_package_module().ReportPackageService


def _sample_report() -> dict:
    return {
        "report_time": "2026-06-09 17:40:00",
        "review_trade_date": "2026-06-09",
        "next_trade_plan_date": "2026-06-10",
        "markdown": "# daily selection\n\n盘后总报告",
        "market_model": {
            "signal_count": 3,
            "executable_count": 1,
            "watch_count": 1,
            "rejected_count": 1,
            "risk_state": "中性偏谨慎",
            "buy_point_type_counts": {"二类做量": 1, "一类冲量": 1},
            "market_distribution": {"sh60": 1, "sz30": 1},
        },
        "data_validation": {
            "confidence": "中",
            "latest_batch_id": "20260609174000",
            "missing_markets": ["sz30"],
            "verified_items": ["日线", "5m", "30m"],
            "unverified_items": ["个股公告"],
            "data_scope": "内部数据版",
        },
        "hotspot_snapshot": {"hotspot_summary": "AI算力 / 机器人"},
        "candidates": [
            {
                "code": "sh.600000",
                "name": "焦点A",
                "selection_status": "focus",
                "final_score": 0.91,
                "structure_status": "结构完整",
                "buy_point_type": "二类做量",
                "close": 10.5,
                "ma25": 10.2,
                "ma25_direction": "向上",
                "price_ma25_deviation_pct": 2.94,
                "vol_ma5": 1500,
                "vol_ma60": 1000,
                "vol_ma5_gt_vol_ma60": True,
                "recent_3d_pct": 3.2,
                "explode_status": "normal",
                "pressure_score": 0.8,
                "intraday_score": 0.7,
                "hot_topic_strength": "strong",
                "position_in_hot_topic": "leader",
                "market_state": "rebound",
                "risk_tags": "公告未验证",
                "logic": "基础条件通过，买点类型二类做量。",
            },
            {
                "code": "sz.300000",
                "name": "观察B",
                "selection_status": "watch",
                "final_score": 0.72,
                "buy_point_type": "一类冲量",
                "hot_topic_strength": "medium",
                "position_in_hot_topic": "strong",
                "explode_status": "warm",
                "market_state": "rebound",
                "risk_tags": "25日线偏离",
                "logic": "仅观察。",
            },
            {
                "code": "sh.600001",
                "name": "淘汰C",
                "selection_status": "reject",
                "reject_reason": "volume_weak",
                "missing_tags_detail": "#缺量：5日均量/量比未达到2560量能要求",
                "logic": "量能不足。",
            },
        ],
        "rejected": [
            {
                "code": "sh.600001",
                "name": "淘汰C",
                "selection_status": "reject",
                "reject_reason": "volume_weak",
                "missing_tags_detail": "#缺量：5日均量/量比未达到2560量能要求",
                "logic": "量能不足。",
            }
        ],
    }


def test_after_market_package_writes_required_files_and_skill_input_without_morning_data(tmp_path):
    result = ReportPackageService(output_root=tmp_path).generate_after_market_package(
        trade_date="2026-06-09",
        report=_sample_report(),
    )

    package_dir = tmp_path / "2026-06-09"
    expected_names = [
        "01_daily_selection.md",
        "02_focus_full_reports.md",
        "03_watch_lite_reports.md",
        "04_scan_summary.json",
        "05_focus_watch_list.json",
        "06_reject_summary.json",
        "07_field_audit.json",
        "08_skill_input.md",
    ]

    assert result["trade_date"] == "2026-06-09"
    assert result["batch_id"] == "20260609174000"
    assert result["status"] == "generated"
    assert [path.name for path in sorted(package_dir.iterdir())] == expected_names
    assert result["files"] == [str(package_dir / name) for name in expected_names]

    skill_input = (package_dir / "08_skill_input.md").read_text(encoding="utf-8")
    assert "## 3. focus 全维度明细" in skill_input
    assert "sh.600000" in skill_input
    assert "基础结构" in skill_input
    assert "量能" in skill_input
    assert "KDJ/MACD" in skill_input
    assert "## 4. watch 简版明细" in skill_input
    assert "sz.300000" in skill_input
    assert "## 5. reject 按原因汇总" in skill_input
    assert "volume_weak" in skill_input
    assert "## 6. 数据质量提示" in skill_input
    assert "sz30" in skill_input
    forbidden = ["集合竞价", "竞价", "早盘", "morning_confirm", "09_morning_confirm", "10_skill_morning_input"]
    assert not any(term in skill_input for term in forbidden)

    scan_summary = json.loads((package_dir / "04_scan_summary.json").read_text(encoding="utf-8"))
    assert scan_summary["distribution"]["selection_status"] == {"focus": 1, "watch": 1, "reject": 1}
    assert scan_summary["data_quality"]["missing_markets"] == ["sz30"]

    focus_watch = json.loads((package_dir / "05_focus_watch_list.json").read_text(encoding="utf-8"))
    assert [item["code"] for item in focus_watch["items"]] == ["sh.600000", "sz.300000"]

    reject_summary = json.loads((package_dir / "06_reject_summary.json").read_text(encoding="utf-8"))
    assert reject_summary == {"trade_date": "2026-06-09", "total_reject": 1, "by_reason": {"volume_weak": 1}}

    field_audit = json.loads((package_dir / "07_field_audit.json").read_text(encoding="utf-8"))
    assert field_audit["fields"]["final_score"]["missing_count"] == 1
    assert field_audit["data_sources"]["daily_package"]["available"] is True
