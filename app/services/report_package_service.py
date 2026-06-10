from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


PACKAGE_FILENAMES = (
    "01_daily_selection.md",
    "02_focus_full_reports.md",
    "03_watch_lite_reports.md",
    "04_scan_summary.json",
    "05_focus_watch_list.json",
    "06_reject_summary.json",
    "07_field_audit.json",
    "08_skill_input.md",
)


class ReportPackageService:
    def __init__(self, output_root: str | Path | None = None):
        self.output_root = Path(output_root or os.getenv("REPORT_PACKAGE_DIR", "reports"))

    def generate_after_market_package(self, trade_date: str, report: dict[str, Any]) -> dict[str, Any]:
        package_dir = self.output_root / trade_date
        package_dir.mkdir(parents=True, exist_ok=True)

        focus = _focus_items(report)
        watch = _watch_items(report)
        rejected = _reject_items(report)
        artifacts = {
            "01_daily_selection.md": render_after_market_daily_selection(trade_date, report, focus, watch, rejected),
            "02_focus_full_reports.md": render_focus_full_reports(trade_date, focus),
            "03_watch_lite_reports.md": render_watch_lite_reports(trade_date, watch),
            "04_scan_summary.json": _to_json(build_scan_summary(trade_date, report, focus, watch, rejected)),
            "05_focus_watch_list.json": _to_json(build_focus_watch_list(trade_date, focus, watch)),
            "06_reject_summary.json": _to_json(build_reject_summary(trade_date, rejected)),
            "07_field_audit.json": _to_json(build_field_audit(trade_date, report, focus + watch + rejected)),
            "08_skill_input.md": render_after_market_skill_input(trade_date, report, focus, watch, rejected),
        }

        files: list[Path] = []
        for filename in PACKAGE_FILENAMES:
            path = package_dir / filename
            path.write_text(artifacts[filename], encoding="utf-8")
            files.append(path)

        return {
            "trade_date": trade_date,
            "batch_id": (report.get("data_validation") or {}).get("latest_batch_id"),
            "status": "generated",
            "files": [str(path) for path in files],
        }

    def generate_after_market_package_from_db(self, db: Any, trade_date: str, limit: int = 50) -> dict[str, Any]:
        from app.services.daily_selection_report import DailySelectionReportService

        report = DailySelectionReportService(db).build_report(limit=limit)
        return self.generate_after_market_package(trade_date=trade_date, report=report)


class DailyReportPackageService:
    def __init__(self, db: Any, output_root: str | Path | None = None):
        self.db = db
        self.service = ReportPackageService(output_root=output_root)

    def generate_daily_package(self, *, trade_date: str, limit: int = 50) -> dict[str, Any]:
        return self.service.generate_after_market_package_from_db(
            db=self.db,
            trade_date=trade_date,
            limit=limit,
        )


def report_package_file_path(*, trade_date: str, filename: str) -> Path:
    return Path(os.getenv("REPORT_PACKAGE_DIR", "reports")) / trade_date / filename


def build_scan_summary(
    trade_date: str,
    report: dict[str, Any],
    focus: list[dict[str, Any]],
    watch: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = list(report.get("candidates") or [])
    data_validation = report.get("data_validation") or {}
    market_model = report.get("market_model") or {}
    return {
        "trade_date": trade_date,
        "batch_id": data_validation.get("latest_batch_id"),
        "total_stocks": market_model.get("signal_count", len(candidates)),
        "distribution": {
            "selection_status": {
                "focus": len(focus),
                "watch": len(watch),
                "reject": len(rejected),
            },
            "explode_status": _count_by(candidates, "explode_status"),
            "market_state": _dominant_value(candidates, "market_state"),
            "hot_topic_strength": _count_by(candidates, "hot_topic_strength"),
            "position_in_hot_topic": _count_by(candidates, "position_in_hot_topic"),
            "buy_point_type": dict(market_model.get("buy_point_type_counts") or {}),
            "market": dict(market_model.get("market_distribution") or {}),
        },
        "data_quality": {
            "confidence": data_validation.get("confidence"),
            "missing_markets": list(data_validation.get("missing_markets") or []),
            "unverified_items": list(data_validation.get("unverified_items") or []),
        },
    }


def build_focus_watch_list(trade_date: str, focus: list[dict[str, Any]], watch: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for status, rows in (("focus", focus), ("watch", watch)):
        for item in rows:
            items.append(
                {
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "selection_status": status,
                    "final_score": item.get("final_score"),
                    "hot_topic_strength": item.get("hot_topic_strength"),
                    "position_in_hot_topic": item.get("position_in_hot_topic"),
                    "explode_status": item.get("explode_status"),
                    "market_state": item.get("market_state"),
                }
            )
    return {"trade_date": trade_date, "items": items}


def build_reject_summary(trade_date: str, rejected: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    for item in rejected:
        reason = item.get("reject_reason") or item.get("missing_tags_detail") or item.get("logic") or "unknown"
        reasons[str(reason)] += 1
    return {"trade_date": trade_date, "total_reject": len(rejected), "by_reason": dict(sorted(reasons.items()))}


def build_field_audit(trade_date: str, report: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    fields = [
        "selection_status",
        "final_score",
        "recent_3d_pct",
        "explode_status",
        "market_state",
        "environment_score",
        "hot_topic_strength",
        "position_in_hot_topic",
        "hot_topic_score",
        "volume_score",
        "structure_score",
        "intraday_score",
        "pressure_score",
    ]
    audit = {
        field: {
            "missing_count": sum(1 for item in items if item.get(field) in (None, "")),
        }
        for field in fields
    }
    return {
        "trade_date": trade_date,
        "fields": audit,
        "data_sources": {
            "daily_package": {
                "available": True,
                "last_update": report.get("report_time"),
            },
            "data_validation": report.get("data_validation") or {},
        },
    }


def render_focus_full_reports(trade_date: str, focus: list[dict[str, Any]]) -> str:
    lines = [f"# 2560 focus 全维度报告 - {trade_date}", ""]
    if not focus:
        lines.append("无 focus 标的。")
        return "\n".join(lines)
    for item in focus:
        lines.extend(_focus_detail_block(item))
    return "\n".join(lines)


def render_watch_lite_reports(trade_date: str, watch: list[dict[str, Any]]) -> str:
    lines = [f"# 2560 watch 简版报告 - {trade_date}", ""]
    if not watch:
        lines.append("无 watch 标的。")
        return "\n".join(lines)
    lines.extend(["| 代码 | 名称 | 分数 | 主线强度 | 位置 | 起爆段 | 风险摘要 |", "|---|---|---:|---|---|---|---|"])
    for item in watch:
        lines.append(
            f"| {_v(item.get('code'))} | {_v(item.get('name'))} | {_fmt_num(item.get('final_score'))} | "
            f"{_v(item.get('hot_topic_strength'))} | {_v(item.get('position_in_hot_topic'))} | "
            f"{_v(item.get('explode_status'))} | {_risk_summary(item)} |"
        )
    return "\n".join(lines)


def render_after_market_skill_input(
    trade_date: str,
    report: dict[str, Any],
    focus: list[dict[str, Any]],
    watch: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> str:
    market_model = report.get("market_model") or {}
    data_validation = report.get("data_validation") or {}
    reject_summary = build_reject_summary(trade_date, rejected)
    detail_appendix = render_skill_input_detail_appendix(trade_date, report, focus, watch, rejected)
    lines = [
        "# 2560 盘后 Skill 输入报告",
        "",
        f"- trade_date: {trade_date}",
        f"- batch_id: {_v(data_validation.get('latest_batch_id'))}",
        f"- report_time: {_v(report.get('report_time'))}",
        "",
        "## 1. 市场环境",
        f"- market_state: {_dominant_value(focus + watch, 'market_state')}",
        f"- risk_state: {_v(market_model.get('risk_state'))}",
        f"- environment_score: {_fmt_num(_first_present(focus + watch, 'environment_score'))}",
        f"- hot_topics: {_v((report.get('hotspot_snapshot') or {}).get('hotspot_summary'))}",
        "",
        "## 2. 候选池概览",
        f"- focus 数量: {len(focus)}",
        f"- watch 数量: {len(watch)}",
        f"- reject 数量: {len(rejected)}",
        "- focus Top: "
        + ("；".join(f"{_v(x.get('code'))} {_fmt_num(x.get('final_score'))} {_v(x.get('hot_topic_strength'))}/{_v(x.get('position_in_hot_topic'))}" for x in focus[:5]) or "-"),
        "",
        "## 3. focus 全维度明细",
    ]
    if focus:
        for item in focus:
            lines.extend(_focus_detail_block(item))
    else:
        lines.append("无 focus 标的。")

    lines.extend(["", "## 4. watch 简版明细"])
    if watch:
        lines.extend(["| 代码 | 名称 | 分数 | 主线 | 位置 | 风险摘要 |", "|---|---|---:|---|---|---|"])
        for item in watch:
            lines.append(
                f"| {_v(item.get('code'))} | {_v(item.get('name'))} | {_fmt_num(item.get('final_score'))} | "
                f"{_v(item.get('hot_topic_strength'))} | {_v(item.get('position_in_hot_topic'))} | {_risk_summary(item)} |"
            )
    else:
        lines.append("无 watch 标的。")

    lines.extend(["", "## 5. reject 按原因汇总"])
    if reject_summary["by_reason"]:
        total = reject_summary["total_reject"] or 1
        for reason, count in reject_summary["by_reason"].items():
            lines.append(f"- {reason}: {count} ({count / total:.1%})")
    else:
        lines.append("- 无")

    lines.extend(["", "## 6. 数据质量提示"])
    lines.append(f"- confidence: {_v(data_validation.get('confidence'))}")
    lines.append(f"- missing_markets: {_join(data_validation.get('missing_markets'))}")
    lines.append(f"- unverified_items: {_join(data_validation.get('unverified_items'))}")
    lines.append(f"- data_scope: {_v(data_validation.get('data_scope'))}")
    lines.extend(["", "## 7. 详细复盘附录", ""])
    lines.extend(detail_appendix)
    return "\n".join(lines)


def render_after_market_daily_selection(
    trade_date: str,
    report: dict[str, Any],
    focus: list[dict[str, Any]],
    watch: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> str:
    existing = str(report.get("markdown") or "").strip()
    if "# 【2560职业短线交易系统 v5.1】盘后复盘与候选说明" in existing:
        return existing
    return "\n".join(_daily_selection_lines(trade_date, report, focus, watch, rejected))


def render_skill_input_detail_appendix(
    trade_date: str,
    report: dict[str, Any],
    focus: list[dict[str, Any]],
    watch: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> list[str]:
    lines = ["### 市场复盘摘要", ""]
    lines.extend(_market_summary_table(report, focus, watch, rejected))
    lines.extend(["", "### 核心候选清单", ""])
    lines.extend(_core_candidate_table(focus, watch))
    lines.extend(["", "### 候选详细说明", ""])
    lines.extend(_candidate_detail_sections(focus, watch))
    lines.extend(["", "### 重点候选（全部符合条件）", ""])
    lines.extend(_focus_bullet_summary(focus))
    lines.extend(["", "### 淘汰原因", ""])
    lines.extend(_reject_summary_lines(rejected))
    lines.extend(["", "## 【10】最终复盘结论", ""])
    lines.extend(_final_conclusion_table(report, focus, watch, rejected, trade_date))
    return lines


def _daily_selection_lines(
    trade_date: str,
    report: dict[str, Any],
    focus: list[dict[str, Any]],
    watch: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> list[str]:
    technical_metadata = report.get("technical_metadata") or {}
    data_validation = report.get("data_validation") or {}
    market_model = report.get("market_model") or {}
    hotspot_snapshot = report.get("hotspot_snapshot") or {}
    lines = [
        "# 【2560职业短线交易系统 v5.1】盘后复盘与候选说明",
        "",
        f"> 报告生成时间：{_v(report.get('report_time'))}",
        "> 报告类型：内部数据版",
        f"> Skill解析版本：{_v(technical_metadata.get('skill_parse_version') or 'daily-selection-skill-v1')}",
        f"> 策略口径：{_v(technical_metadata.get('strategy_contract') or '2560标准候选口径')}",
        f"> 数据截止：复盘交易日 {_v(report.get('review_trade_date') or trade_date)}",
        f"> 观察日期：下一个A股交易日 {_v(report.get('next_trade_plan_date'))}",
        "",
        "## 【0】数据核验摘要",
        "",
        "| 项目 | 结果 |",
        "|------|------|",
        f"| 最新2560批次 | {_v(data_validation.get('latest_batch_id'))} |",
        f"| 数据置信度 | {_v(data_validation.get('confidence'))} |",
        f"| 已验证项目 | {_join(data_validation.get('verified_items'))} |",
        f"| 无法验证项目 | {_join(data_validation.get('unverified_items'))} |",
        f"| 数据范围 | {_v(data_validation.get('data_scope'))} |",
        f"| 公告/研报策略 | {_v(technical_metadata.get('announcement_policy') or '默认禁止逐票联网公告/研报调用')} |",
        "",
        "## 【1】市场量化模型",
        "",
        "| 指标 | 数值 | 依据 |",
        "|------|------|------|",
        f"| 风险状态 | {_v(market_model.get('risk_state'))} | 内部候选与淘汰比例 |",
        f"| 2560候选数量 | {market_model.get('signal_count', len(focus) + len(watch) + len(rejected))} | 最新 selected_signal |",
        f"| focus/watch/reject | {len(focus)} / {len(watch)} / {len(rejected)} | 候选分层 |",
        f"| 买点类型分布 | {_format_distribution(market_model.get('buy_point_type_counts') or {})} | 日线MAVOL5/60节奏 |",
        f"| 市场分布 | {_format_distribution(market_model.get('market_distribution') or {})} | 代码前缀 |",
        "",
        "## 【2】今日热点主线",
        "",
        "| 项目 | 结果 |",
        "|------|------|",
        f"| 热点摘要 | {_v(hotspot_snapshot.get('hotspot_summary') or '热点主线未验证')} |",
        f"| 主导市场状态 | {_v(_dominant_value(focus + watch, 'market_state'))} |",
        "",
    ]
    lines.extend(["## 【3】外部事实核验", ""])
    lines.extend(_external_context_lines(report, focus, watch))
    lines.extend(["", "## 【5】核心候选清单", ""])
    lines.extend(_core_candidate_table(focus, watch))
    lines.extend(["", "## 【6】2560准量化候选明细", ""])
    lines.extend(_candidate_detail_sections(focus, watch))
    lines.extend(["", "## 【7】重点候选与淘汰原因", "", "### 重点候选（全部符合条件）", ""])
    lines.extend(_focus_bullet_summary(focus))
    lines.extend(["", "### 淘汰原因", ""])
    lines.extend(_reject_summary_lines(rejected))
    lines.extend(["", "## 【10】最终复盘结论", ""])
    lines.extend(_final_conclusion_table(report, focus, watch, rejected, trade_date))
    lines.extend(["", "## 【合规声明】", "", "本报告仅用于盘后复盘与下一观察日条件核验。"])
    return lines


def _market_summary_table(
    report: dict[str, Any],
    focus: list[dict[str, Any]],
    watch: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> list[str]:
    market_model = report.get("market_model") or {}
    hotspot_snapshot = report.get("hotspot_snapshot") or {}
    return [
        "| 项目 | 结果 |",
        "|------|------|",
        f"| 风险状态 | {_v(market_model.get('risk_state'))} |",
        f"| focus/watch/reject | {len(focus)} / {len(watch)} / {len(rejected)} |",
        f"| 主导市场状态 | {_v(_dominant_value(focus + watch, 'market_state'))} |",
        f"| 热点摘要 | {_v(hotspot_snapshot.get('hotspot_summary'))} |",
    ]


def _external_context_lines(report: dict[str, Any], focus: list[dict[str, Any]], watch: list[dict[str, Any]]) -> list[str]:
    context = report.get("external_context") or {}
    source_status = context.get("source_status") or {}
    lines = [
        "| 项目 | 结果 |",
        "|------|------|",
        f"| 市场温度 | {_v(context.get('market_temperature') or '外部市场温度未验证')} |",
        f"| 指数表现 | {_v(context.get('index_summary') or '指数表现未验证')} |",
        f"| 成交额 | {_v(context.get('turnover_summary') or '成交额未验证')} |",
        f"| 涨跌家数 | {_v(context.get('breadth_summary') or '涨跌家数未验证')} |",
        f"| 热点快照 | {_v(context.get('hotspot_summary') or (report.get('hotspot_snapshot') or {}).get('hotspot_summary') or '热点主线未验证')} |",
        f"| 快照时间 | {_v(context.get('snapshot_time'))} |",
        "",
        "| 数据源 | 状态 |",
        "|--------|------|",
        f"| EastMoney | {_v(source_status.get('eastmoney') or 'unverified')} |",
        f"| cninfo | {_v(source_status.get('cninfo') or 'unverified')} |",
        f"| 妙想/妙梦 | {_v(source_status.get('miaoxiang') or 'unverified')} |",
        "",
    ]
    lines.extend(_external_evidence_rows(focus, watch))
    return lines


def _external_evidence_rows(focus: list[dict[str, Any]], watch: list[dict[str, Any]]) -> list[str]:
    rows = focus + watch
    if not rows:
        return ["无 focus/watch 候选，未查询外部事实。"]
    lines = [
        "| 代码 | 名称 | 热点匹配 | 热点主题 | 公告摘要 | 个股事实摘要 | 证据质量 |",
        "|------|------|----------|----------|----------|--------------|----------|",
    ]
    for item in rows:
        evidence = item.get("external_evidence") or {}
        lines.append(
            f"| {_v(item.get('code'))} | {_v(item.get('name'))} | "
            f"{_v(evidence.get('hotspot_match_level') or 'unverified')} | "
            f"{_v(evidence.get('hotspot_theme'))} | "
            f"{_v(evidence.get('announcement_summary') or '公告未验证')} | "
            f"{_v(evidence.get('stock_fact_summary') or '外部事实未验证')} | "
            f"{_v(evidence.get('evidence_quality') or 'unverified')} |"
        )
    return lines


def _core_candidate_table(focus: list[dict[str, Any]], watch: list[dict[str, Any]]) -> list[str]:
    rows = focus + watch
    if not rows:
        return ["无候选标的。"]
    lines = [
        "| 代码 | 名称 | selection_status | final_score | recent_3d_pct | explode_status | hot_topic_strength | position_in_hot_topic | 报告判断 |",
        "|------|------|------------------|-------------|---------------|----------------|--------------------|-----------------------|----------|",
    ]
    for item in rows:
        lines.append(
            f"| {_v(item.get('code'))} | {_v(item.get('name'))} | {_status_label(item)} | "
            f"{_fmt_num(item.get('final_score'))} | {_fmt_num(item.get('recent_3d_pct') or item.get('recent_3day_gain_pct'))} | "
            f"{_v(item.get('explode_status'))} | {_v(item.get('hot_topic_strength'))} | "
            f"{_v(item.get('position_in_hot_topic'))} | {_v(item.get('report_action_label') or item.get('logic'))} |"
        )
    return lines


def _candidate_detail_sections(focus: list[dict[str, Any]], watch: list[dict[str, Any]]) -> list[str]:
    rows = focus + watch
    if not rows:
        return ["无候选详细说明。"]
    lines: list[str] = []
    for item in rows:
        lines.extend(
            [
                f"### 标的：{_v(item.get('name'))}（{_v(item.get('code'))}）",
                "",
                "| 项目 | 内容 |",
                "|------|------|",
                f"| 2560状态 | {_v(item.get('structure_status'))} |",
                f"| 策略评估状态 | {_status_label(item)} |",
                f"| 策略总分 | {_fmt_num(item.get('final_score'))} |",
                f"| 买点类型 | {_v(item.get('buy_point_type'))} |",
                f"| 近3日涨幅 / 起爆状态 | {_fmt_num(item.get('recent_3d_pct') or item.get('recent_3day_gain_pct'))} / {_v(item.get('explode_status'))} |",
                f"| 市场环境 / 环境分 | {_v(item.get('market_state'))} / {_fmt_num(item.get('environment_score'))} |",
                f"| 题材强度 / 题材地位 | {_v(item.get('hot_topic_strength'))} / {_v(item.get('position_in_hot_topic'))} |",
                f"| 收盘价 / 25日线 | {_fmt_num(item.get('close'))} / {_fmt_num(item.get('ma25'))} |",
                f"| 25日线位置% | {_fmt_num(item.get('price_ma25_deviation_pct'))} |",
                f"| 5日均量线 / 60日均量线 | {_fmt_num(item.get('vol_ma5'), 0)} / {_fmt_num(item.get('vol_ma60'), 0)} |",
                f"| 5量>60量 | {_fmt_bool(item.get('vol_ma5_gt_vol_ma60'))} |",
                f"| 风险标签 | {_v(item.get('risk_tags') or item.get('missing_tags_detail'))} |",
                f"| 候选类型 | {_v(item.get('trade_type') or item.get('selection_status'))} |",
                f"| 逻辑 | {_v(item.get('logic'))} |",
                "",
            ]
        )
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _focus_bullet_summary(focus: list[dict[str, Any]]) -> list[str]:
    if not focus:
        return ["无符合条件的重点候选。"]
    return [f"- {_v(item.get('code'))} {_v(item.get('name'))}：{_v(item.get('logic'))}" for item in focus]


def _reject_summary_lines(rejected: list[dict[str, Any]]) -> list[str]:
    if not rejected:
        return ["- 无"]
    return [
        f"- {_v(item.get('code'))} {_v(item.get('name'))}：{_v(item.get('reject_reason') or item.get('logic') or item.get('missing_tags_detail'))}"
        for item in rejected
    ]


def _final_conclusion_table(
    report: dict[str, Any],
    focus: list[dict[str, Any]],
    watch: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    trade_date: str,
) -> list[str]:
    market_model = report.get("market_model") or {}
    final_advice = report.get("final_advice") or {}
    summary = f"复盘交易日 {trade_date}：focus {len(focus)} 只，watch {len(watch)} 只，reject {len(rejected)} 只。"
    return [
        "| 项目 | 结论 |",
        "|------|------|",
        f"| 最终策略 | {_v(final_advice.get('strategy') or market_model.get('risk_state') or '观察筛选')} |",
        f"| 是否继续跟踪 | {_v(final_advice.get('open_new_position') or ('是' if focus or watch else '否'))} |",
        f"| 重点候选数量 | {len(focus)} |",
        f"| 一句话结论 | {_v(summary)} |",
    ]


def _focus_detail_block(item: dict[str, Any]) -> list[str]:
    return [
        "",
        f"### {_v(item.get('code'))} {_v(item.get('name'))}",
        f"- 基础结构: selection_status={_status_label(item)}; structure={_v(item.get('structure_status'))}; ma25_direction={_v(item.get('ma25_direction'))}; ma25_deviation_pct={_fmt_num(item.get('price_ma25_deviation_pct'))}",
        f"- 量能: vol_ma5={_fmt_num(item.get('vol_ma5'), 0)}; vol_ma60={_fmt_num(item.get('vol_ma60'), 0)}; vol_ma5_gt_vol_ma60={_fmt_bool(item.get('vol_ma5_gt_vol_ma60'))}; buy_point_type={_v(item.get('buy_point_type'))}",
        f"- 起爆段: recent_3d_pct={_fmt_num(item.get('recent_3d_pct') or item.get('recent_3day_gain_pct'))}; explode_status={_v(item.get('explode_status'))}",
        f"- 30m 压力距离%: {_fmt_num(item.get('pressure_distance_pct') or item.get('pressure_score'))}",
        f"- 5m 确认状态: {_v(item.get('intraday_status') or item.get('intraday_score'))}",
        f"- KDJ/MACD: kdj_j={_fmt_num(item.get('kdj_j'))}; macd_hist={_fmt_num(item.get('macd_hist'))}",
        f"- 热点主线: strength={_v(item.get('hot_topic_strength'))}; position={_v(item.get('position_in_hot_topic'))}; score={_fmt_num(item.get('hot_topic_score'))}",
        f"- 风控区间: entry={_v(item.get('entry_zone'))}; risk={_v(item.get('risk_control_price') or item.get('stop_loss'))}",
        f"- 综合评分及理由: final_score={_fmt_num(item.get('final_score'))}; logic={_v(item.get('logic'))}",
    ]


def _focus_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    source = list(report.get("candidates") or [])
    return sorted([item for item in source if _status_label(item) == "focus"], key=_score_sort_key)


def _watch_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    source = list(report.get("candidates") or [])
    return sorted([item for item in source if _status_label(item) == "watch"], key=_score_sort_key)


def _reject_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    source = list(report.get("rejected") or [])
    if not source:
        source = [item for item in report.get("candidates") or [] if _status_label(item) == "reject"]
    return source


def _status_label(item: dict[str, Any]) -> str:
    status = str(item.get("selection_status") or "").lower()
    bucket = str(item.get("bucket") or "")
    if bucket == "可执行":
        return "focus"
    if bucket == "观察":
        return "watch"
    if bucket == "淘汰":
        return "reject"
    if status in {"focus", "watch", "reject"}:
        return status
    return status or "unknown"


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        value = item.get(key)
        if value in (None, ""):
            continue
        counts[str(value)] += 1
    return dict(sorted(counts.items()))


def _dominant_value(items: list[dict[str, Any]], key: str) -> str | None:
    counts = _count_by(items, key)
    if not counts:
        return None
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]


def _first_present(items: list[dict[str, Any]], key: str) -> Any:
    for item in items:
        if item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _score_sort_key(item: dict[str, Any]) -> tuple[float, str]:
    try:
        score = float(item.get("final_score") or 0)
    except Exception:
        score = 0.0
    return (-score, str(item.get("code") or ""))


def _risk_summary(item: dict[str, Any]) -> str:
    return _v(item.get("risk_tags") or item.get("reject_reason") or item.get("missing_tags_detail") or item.get("logic"))


def _format_distribution(dist: dict[str, int]) -> str:
    if not dist:
        return "-"
    return " / ".join(f"{_v(key)}:{value}" for key, value in dist.items())


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        if value is None or value == "":
            return "-"
        number = float(value)
    except Exception:
        return _v(value)
    if digits <= 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _fmt_bool(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return "无法验证"


def _join(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, (list, tuple, set)):
        return " / ".join(_v(item) for item in value)
    return _v(value)


def _v(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("\x00", "").strip()


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
