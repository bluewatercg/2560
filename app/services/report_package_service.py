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
            "01_daily_selection.md": str(report.get("markdown") or ""),
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
    return "\n".join(lines)


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
    if status in {"focus", "watch", "reject"}:
        return status
    if bucket == "可执行":
        return "focus"
    if bucket == "观察":
        return "watch"
    if bucket == "淘汰":
        return "reject"
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
