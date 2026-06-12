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
        "09_simple_2560_hard_metrics.md",
    ]

    assert result["trade_date"] == "2026-06-09"
    assert result["batch_id"] == "20260609174000"
    assert result["status"] == "generated"
    assert [path.name for path in sorted(package_dir.iterdir())] == expected_names
    assert result["files"] == [str(package_dir / name) for name in expected_names]

    daily_selection = (package_dir / "01_daily_selection.md").read_text(encoding="utf-8")
    assert "# 【2560职业短线交易系统 v5.1】盘后复盘与候选说明" in daily_selection
    assert "## 【5】核心候选清单" in daily_selection
    assert "## 【6】2560准量化候选明细" in daily_selection
    assert "### 标的：焦点A（sh.600000）" in daily_selection
    assert "## 【7】重点候选与淘汰原因" in daily_selection
    assert "## 【10】最终复盘结论" in daily_selection

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
    assert "## 7. 详细复盘附录" in skill_input
    assert "### 标的：焦点A（sh.600000）" in skill_input
    assert "### 重点候选（全部符合条件）" in skill_input
    assert "### 淘汰原因" in skill_input
    assert "## 【10】最终复盘结论" in skill_input
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

    simple_report = (package_dir / "09_simple_2560_hard_metrics.md").read_text(encoding="utf-8")
    assert "只显示：收盘价高于25日均价、5日平均成交量高于60日平均成交量、近3日涨幅不超过20%" in simple_report
    assert "短期量能倍数说明：例如 1.55 表示最近5日平均成交量是60日平均成交量的1.55倍" in simple_report
    assert "| 代码 | 名称 | 收盘价 | 25日均价 | 高于25日均价幅度 | 近3日涨幅 | 5日平均成交量 | 60日平均成交量 | 短期量能倍数 |" in simple_report
    assert "MA25" not in simple_report
    assert "MAVOL5" not in simple_report
    assert "MAVOL60" not in simple_report
    assert "| sh.600000 | 焦点A | 10.50 | 10.20 | 2.94% | 3.20% | 1500 | 1000 | 1.50 |" in simple_report


def test_report_package_groups_by_execution_bucket_when_selection_status_conflicts(tmp_path):
    report = _sample_report()
    report["candidates"] = [
        {
            "code": "sh.600350",
            "name": "山东高速",
            "bucket": "可执行",
            "selection_status": "reject",
            "final_score": 0.54,
            "buy_point_type": "二类做量",
            "logic": "基础条件通过，买点类型二类做量。",
        },
        {
            "code": "sz.002832",
            "name": "比音勒芬",
            "bucket": "观察",
            "selection_status": "reject",
            "final_score": 0.41,
            "buy_point_type": "一类冲量",
            "logic": "基础条件通过，买点类型一类冲量。",
        },
    ]
    report["rejected"] = []

    ReportPackageService(output_root=tmp_path).generate_after_market_package(
        trade_date="2026-06-10",
        report=report,
    )

    package_dir = tmp_path / "2026-06-10"
    focus_report = (package_dir / "02_focus_full_reports.md").read_text(encoding="utf-8")
    watch_report = (package_dir / "03_watch_lite_reports.md").read_text(encoding="utf-8")
    focus_watch = json.loads((package_dir / "05_focus_watch_list.json").read_text(encoding="utf-8"))
    scan_summary = json.loads((package_dir / "04_scan_summary.json").read_text(encoding="utf-8"))

    assert "sh.600350" in focus_report
    assert "sz.002832" in watch_report
    assert [item["code"] for item in focus_watch["items"]] == ["sh.600350", "sz.002832"]
    assert scan_summary["distribution"]["selection_status"] == {"focus": 1, "watch": 1, "reject": 0}


def test_daily_selection_renders_external_evidence_section(tmp_path):
    report = _sample_report()
    report["external_context"] = {
        "market_temperature": "创业板指下跌2.29%，热点分化",
        "index_summary": "沪指下跌0.58%",
        "turnover_summary": "两市半日成交17302亿元",
        "breadth_summary": "上涨1112家，下跌4346家，55只涨停",
        "hotspot_summary": "机器人 / 算力",
        "snapshot_time": "2026-06-09 17:42:00",
        "source_status": {"eastmoney": "ok", "cninfo": "ok", "miaoxiang": "ok"},
    }
    report["candidates"][0]["external_evidence"] = {
        "hotspot_match_level": "strong",
        "hotspot_theme": "机器人",
        "hotspot_reason": "热点强匹配：机器人",
        "announcement_status": "ok",
        "announcement_sentiment": "bearish",
        "announcement_summary": "最新公告：利空｜焦点A股东拟减持",
        "announcement_source": "cninfo",
        "stock_fact_summary": "焦点A：主力资金净流入",
        "industry_theme_summary": "机器人概念",
        "valuation_summary": "估值未验证",
        "capital_flow_summary": "主力资金净流入",
        "evidence_quality": "official",
    }

    ReportPackageService(output_root=tmp_path).generate_after_market_package(
        trade_date="2026-06-09",
        report=report,
    )

    daily_selection = (tmp_path / "2026-06-09" / "01_daily_selection.md").read_text(encoding="utf-8")

    assert "## 【3】外部事实核验" in daily_selection
    assert "| EastMoney | ok |" in daily_selection
    assert "| cninfo | ok |" in daily_selection
    assert "| 妙想/妙梦 | ok |" in daily_selection
    assert "| sh.600000 | 焦点A | strong | 机器人 | 最新公告：利空｜焦点A股东拟减持 | 焦点A：主力资金净流入 | official |" in daily_selection


def test_after_market_skill_input_final_conclusion_uses_focus_watch_reject_counts(tmp_path):
    report = _sample_report()
    report["market_model"] = {
        **report["market_model"],
        "executable_count": 7,
        "watch_count": 1,
        "rejected_count": 21,
    }
    report["final_advice"] = {
        "strategy": "主线交易",
        "open_new_position": "是",
        "summary": "内部2560候选29只，可执行7只，观察1只，淘汰21只。",
    }

    ReportPackageService(output_root=tmp_path).generate_after_market_package(
        trade_date="2026-06-09",
        report=report,
    )

    skill_input = (tmp_path / "2026-06-09" / "08_skill_input.md").read_text(encoding="utf-8")

    assert "| 重点候选数量 | 1 |" in skill_input
    assert "| 一句话结论 | 复盘交易日 2026-06-09：focus 1 只，watch 1 只，reject 1 只。 |" in skill_input
    assert "可执行7只，观察1只，淘汰21只" not in skill_input
