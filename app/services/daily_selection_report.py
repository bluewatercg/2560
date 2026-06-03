from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.services.annotation_engine_2568 import AnnotationEngine2568


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _market_from_code(code: str | None) -> str:
    c = (code or "").lower()
    if c.startswith("sh.60"):
        return "sh60"
    if c.startswith("sh.68"):
        return "sh68"
    if c.startswith("sz.00"):
        return "sz00"
    if c.startswith("sz.30"):
        return "sz30"
    return "unknown"


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    ann = candidate.get("annotation") or {}
    structure_status = candidate.get("structure_status") or ""
    missing_count = _int(candidate.get("missing_tag_count"))
    raw_score = _num(candidate.get("strength_score_raw"), 50.0)
    a_count = _int(ann.get("a_count"))
    b_count = _int(ann.get("b_count"))
    d_count = _int(ann.get("d_count"))
    action = ann.get("manual_action_label") or ""
    level = ann.get("highlight_level") or ""

    score = raw_score
    if structure_status == "结构完整":
        score += 12
    elif structure_status == "部分满足":
        score += 4
    score += a_count * 8 + b_count * 4
    score -= min(missing_count * 5, 25)
    score -= d_count * 7
    if "风险较多" in action or str(level).startswith("D"):
        score -= 18
    score = max(0, min(100, round(score)))

    if score >= 75 and d_count <= 1 and ("重点关注" in action or "可关注" in action):
        bucket = "可执行"
        trade_type = "轻仓试错"
    elif score >= 58 and d_count <= 2 and "建议移出" not in action:
        bucket = "观察"
        trade_type = "仅观察"
    else:
        bucket = "淘汰"
        trade_type = "放弃"

    reject_reason = ""
    if bucket == "淘汰":
        reasons = []
        if action:
            reasons.append(action)
        if d_count >= 3:
            reasons.append(f"D项较多({d_count})")
        if missing_count:
            reasons.append(f"缺失条件{missing_count}项")
        reject_reason = "；".join(reasons) or "综合评分不足"

    logic_parts = []
    if structure_status:
        logic_parts.append(structure_status)
    if action:
        logic_parts.append(f"2568 标注{action}")
    if missing_count:
        logic_parts.append(f"缺失条件{missing_count}项")
    if d_count:
        logic_parts.append(f"风险项{d_count}个")

    return {
        "report_score": score,
        "bucket": bucket,
        "trade_type": trade_type,
        "reject_reason": reject_reason,
        "logic": "，".join(logic_parts) + "。",
    }


def build_internal_market_model(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    signal_count = len(candidates)
    executable_count = sum(1 for x in candidates if x.get("bucket") == "可执行")
    watch_count = sum(1 for x in candidates if x.get("bucket") == "观察")
    rejected_count = sum(1 for x in candidates if x.get("bucket") == "淘汰")
    complete_count = sum(1 for x in candidates if x.get("structure_status") == "结构完整")
    partial_count = sum(1 for x in candidates if x.get("structure_status") == "部分满足")
    avg_score = round(sum(_num(x.get("report_score")) for x in candidates) / signal_count, 1) if signal_count else 0

    market_distribution: dict[str, int] = {}
    for x in candidates:
        market = _market_from_code(x.get("code"))
        market_distribution[market] = market_distribution.get(market, 0) + 1

    temperature = min(100, round(signal_count * 2 + executable_count * 12 + watch_count * 5 + avg_score * 0.35))
    if temperature >= 75 and executable_count >= 3:
        risk_state = "风险可控"
    elif temperature >= 45 and executable_count:
        risk_state = "中性偏谨慎"
    elif signal_count:
        risk_state = "弱机会"
    else:
        risk_state = "没有明确交易机会"

    return {
        "temperature": temperature,
        "crowding": None,
        "risk_state": risk_state,
        "signal_count": signal_count,
        "complete_count": complete_count,
        "partial_count": partial_count,
        "executable_count": executable_count,
        "watch_count": watch_count,
        "rejected_count": rejected_count,
        "average_score": avg_score,
        "market_distribution": market_distribution,
        "basis": "内部2560命中数量、结构完整比例、2568强弱标注、淘汰比例",
    }


def _compact_missing_tags(v: Any) -> str:
    if not v:
        return ""
    if isinstance(v, list):
        return " / ".join(str(x) for x in v)
    return str(v)


class DailySelectionReportService:
    def __init__(self, db: Session):
        self.db = db

    def build_report(self, limit: int = 50) -> dict[str, Any]:
        now = datetime.now()
        latest_batch = self._latest_batch()
        signals = self._latest_selected_signals(latest_batch, limit) if latest_batch else []
        annotations = self._annotations_for_codes([s["code"] for s in signals])
        candidates = []
        for s in signals:
            ann = annotations.get(s["code"], {})
            item = {
                **s,
                "market": _market_from_code(s.get("code")),
                "missing_tags_text": _compact_missing_tags(s.get("missing_tags")),
                "annotation": ann,
                "highlight_level": ann.get("highlight_level"),
                "manual_action_label": ann.get("manual_action_label"),
                "highlight_summary": ann.get("highlight_summary"),
                "risk_tags": ann.get("risk_tags"),
                "ma25_status": ann.get("ma25_status"),
                "ma60_status": ann.get("ma60_status"),
                "volume_status": ann.get("volume_status"),
                "trend_status": ann.get("trend_status"),
                "close": ann.get("close") if ann.get("close") is not None else s.get("price"),
                "volume": ann.get("volume"),
                "amount": ann.get("amount"),
                "ma25": ann.get("ma25"),
                "ma60": ann.get("ma60"),
                "ma25_direction": ann.get("ma25_direction"),
                "ma60_direction": ann.get("ma60_direction"),
                "price_ma25_deviation_pct": ann.get("price_ma25_deviation_pct"),
                "vol_ma5": ann.get("vol_ma5"),
                "vol_ma60": ann.get("vol_ma60"),
                "vol_ma5_gt_vol_ma60": ann.get("vol_ma5_gt_vol_ma60"),
                "vol_ratio": ann.get("vol_ratio"),
            }
            item.update(classify_candidate(item))
            candidates.append(item)

        candidates.sort(key=lambda x: (_bucket_rank(x.get("bucket")), -_num(x.get("report_score"))))
        market_model = build_internal_market_model(candidates)
        data_validation = self._data_validation(latest_batch, market_model)
        executable = [x for x in candidates if x["bucket"] == "可执行"][:3]
        watchlist = [x for x in candidates if x["bucket"] == "观察"]
        rejected = [x for x in candidates if x["bucket"] == "淘汰"]

        report = {
            "title": "内部数据版 2560 盘后选股报告",
            "system_version": "v5.1-internal",
            "report_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "review_trade_date": self._review_trade_date(latest_batch, now),
            "next_trade_plan_date": self._next_plan_date(now),
            "data_validation": data_validation,
            "market_model": market_model,
            "core_candidates": candidates[:5],
            "candidates": candidates,
            "executable": executable,
            "watchlist": watchlist,
            "rejected": rejected,
            "final_advice": self._final_advice(market_model),
        }
        report["markdown"] = render_markdown_report(report)
        return report

    def _latest_batch(self) -> dict[str, Any] | None:
        row = self.db.execute(text("""
            SELECT batch_id, run_time, strategy_code, strategy_version, status, message
            FROM analysis_batch
            WHERE strategy_code='S2560' AND status='success'
            ORDER BY run_time DESC
            LIMIT 1
        """)).mappings().first()
        return dict(row) if row else None

    def _latest_selected_signals(self, latest_batch: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        sql = text("""
            SELECT a.id, a.batch_id, a.code, a.name, a.signal_time, a.signal_period,
                   a.price, a.structure_status, a.strength_score_raw, a.missing_tags,
                   a.missing_tag_count, a.explain_text, a.data_quality_status,
                   a.selected_signal, s.industry_name, s.board_name
            FROM structure_2560_analysis a
            LEFT JOIN stock_info s ON s.code=a.code
            WHERE CAST(a.batch_id AS CHAR)=CAST(:batch_id AS CHAR)
              AND a.selected_signal=1
            ORDER BY COALESCE(a.strength_score_raw, 0) DESC, a.signal_time DESC, a.id DESC
            LIMIT :limit
        """)
        rows = self.db.execute(sql, {"batch_id": latest_batch["batch_id"], "limit": limit}).mappings().all()
        return [dict(r) for r in rows]

    def _annotations_for_codes(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}
        engine = AnnotationEngine2568(self.db)
        return {x.get("code"): x for x in engine.annotations_for_codes(codes).get("items", [])}

    def _data_validation(self, latest_batch: dict[str, Any] | None, market_model: dict[str, Any]) -> dict[str, Any]:
        readiness = []
        try:
            rows = self.db.execute(text("""
                SELECT market, daily_latest, k5m_latest, k30m_latest,
                       daily_status, k5m_status, k30m_status
                FROM workspace_status
                ORDER BY market
            """)).mappings().all()
            readiness = [dict(r) for r in rows]
        except Exception:
            readiness = []

        missing_markets = [
            r.get("market")
            for r in readiness
            if not (r.get("daily_latest") and r.get("k5m_latest") and r.get("k30m_latest"))
        ]
        unverified_items = ["指数锚点", "市场涨跌停宽度", "热点主线", "账户风控", "北向/两融", "个股公告"]
        if not latest_batch:
            confidence = "低"
        elif missing_markets:
            confidence = "中"
        elif market_model.get("signal_count", 0) <= 0:
            confidence = "中"
        else:
            confidence = "高"

        return {
            "confidence": confidence,
            "latest_batch_id": latest_batch.get("batch_id") if latest_batch else None,
            "latest_batch_run_time": latest_batch.get("run_time") if latest_batch else None,
            "market_readiness": readiness,
            "missing_markets": missing_markets,
            "verified_items": ["日线", "5m", "30m", "2560核心", "2568标注", "代码名称校验"],
            "unverified_items": unverified_items,
            "data_scope": "内部数据版：不含外部指数、账户、北向、两融、公告联网校验",
        }

    @staticmethod
    def _review_trade_date(latest_batch: dict[str, Any] | None, now: datetime) -> str:
        run_time = latest_batch.get("run_time") if latest_batch else None
        try:
            return run_time.strftime("%Y-%m-%d")
        except Exception:
            return now.strftime("%Y-%m-%d")

    @staticmethod
    def _next_plan_date(now: datetime) -> str:
        d = now + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    @staticmethod
    def _final_advice(model: dict[str, Any]) -> dict[str, str]:
        if model["executable_count"] >= 3 and model["temperature"] >= 70:
            strategy = "主线交易"
            open_new = "是"
        elif model["executable_count"] > 0:
            strategy = "震荡"
            open_new = "是，但必须满足次日条件"
        elif model["watch_count"] > 0:
            strategy = "等待"
            open_new = "否，仅观察"
        else:
            strategy = "防守"
            open_new = "否"
        return {
            "strategy": strategy,
            "open_new_position": open_new,
            "summary": f"内部2560候选{model['signal_count']}只，可执行{model['executable_count']}只，观察{model['watch_count']}只，淘汰{model['rejected_count']}只。",
        }


def _bucket_rank(bucket: str | None) -> int:
    return {"可执行": 0, "观察": 1, "淘汰": 2}.get(bucket or "", 9)


def render_markdown_report(report: dict[str, Any]) -> str:
    dv = report.get("data_validation") or {}
    mm = report.get("market_model") or {}
    final = report.get("final_advice") or {}
    lines = [
        "# 【2560职业短线交易系统 v5.1】盘后复盘与交易预案",
        "",
        f"> 报告生成时间：{report.get('report_time', '-')}",
        "> 报告类型：内部数据版",
        f"> 数据截止：复盘交易日 {report.get('review_trade_date', '-')}",
        f"> 交易预案：下一个A股交易日 {report.get('next_trade_plan_date', '-')}",
        "",
        "## 【0】数据核验摘要",
        "",
        "| 项目 | 结果 |",
        "|------|------|",
        f"| 最新2560批次 | {dv.get('latest_batch_id') or '-'} |",
        f"| 数据置信度 | {dv.get('confidence') or '-'} |",
        f"| 已验证项目 | {' / '.join(dv.get('verified_items') or [])} |",
        f"| 无法验证项目 | {' / '.join(dv.get('unverified_items') or [])} |",
        f"| 数据范围 | {dv.get('data_scope') or '-'} |",
        "",
        "## 【1】市场量化模型",
        "",
        "| 指标 | 数值 | 依据 |",
        "|------|------|------|",
        f"| 市场温度 | {mm.get('temperature', '-')} | {mm.get('basis', '-')} |",
        f"| 市场拥挤度 | 无外部数据 | 第一版暂不计算 |",
        f"| 风险状态 | {mm.get('risk_state', '-')} | 内部候选与淘汰比例 |",
        f"| 2560候选数量 | {mm.get('signal_count', 0)} | 最新 selected_signal |",
        f"| 市场分布 | {_format_distribution(mm.get('market_distribution') or {})} | 代码前缀 |",
        "",
        "## 【5】核心交易候选",
        "",
    ]
    core = report.get("core_candidates") or []
    if core:
        lines.extend([
            "| 代码 | 名称 | 分组 | 评分 | 收盘价 | 25日线 | 距离25日线% | 25日方向 | 当日成交量 | 5日均量线 | 60日均量线 | 5量>60量 | 2560状态 | 2568建议 |",
            "|------|------|------|------|--------|--------|-------------|----------|------------|------------|-------------|----------|----------|----------|",
        ])
        for x in core:
            lines.append(
                f"| {x.get('code','-')} | {x.get('name','-')} | {x.get('bucket','-')} | "
                f"{x.get('report_score','-')} | {_fmt_num(x.get('close'))} | {_fmt_num(x.get('ma25'))} | "
                f"{_fmt_num(x.get('price_ma25_deviation_pct'))} | {x.get('ma25_direction') or '-'} | "
                f"{_fmt_num(x.get('volume'), 0)} | {_fmt_num(x.get('vol_ma5'), 0)} | {_fmt_num(x.get('vol_ma60'), 0)} | "
                f"{_fmt_bool(x.get('vol_ma5_gt_vol_ma60'))} | {x.get('structure_status','-')} | "
                f"{x.get('manual_action_label','-')} |"
            )
    else:
        lines.append("无符合内部 2560 候选条件的标的。")

    lines.extend(["", "## 【6】2560准量化交易明细", ""])
    for x in core:
        lines.extend([
            f"### 标的：{x.get('name','-')}（{x.get('code','-')}）",
            "",
            "| 项目 | 内容 |",
            "|------|------|",
            f"| 所属行业/板块 | {x.get('industry_name') or '-'} / {x.get('board_name') or '-'} |",
            f"| 2560状态 | {x.get('structure_status') or '-'} |",
            f"| 2560评分 | {x.get('report_score') or '-'} |",
            f"| 缺失条件 | {x.get('missing_tags_text') or '-'} |",
            f"| 收盘价 | {_fmt_num(x.get('close'))} |",
            f"| 25日价格均线 | {_fmt_num(x.get('ma25'))} |",
            f"| 25日方向 | {x.get('ma25_direction') or '-'} |",
            f"| 距离25日线% | {_fmt_num(x.get('price_ma25_deviation_pct'))} |",
            f"| 当日成交量 | {_fmt_num(x.get('volume'), 0)} |",
            f"| 5日均量线 | {_fmt_num(x.get('vol_ma5'), 0)} |",
            f"| 60日均量线 | {_fmt_num(x.get('vol_ma60'), 0)} |",
            f"| 5日均量线是否在60日均量线上方 | {_fmt_bool(x.get('vol_ma5_gt_vol_ma60'))} |",
            f"| 量比 | {_fmt_num(x.get('vol_ratio'))} |",
            f"| 2568等级 | {x.get('highlight_level') or '-'} |",
            f"| 2568建议 | {x.get('manual_action_label') or '-'} |",
            f"| MA25/MA60 | {x.get('ma25_status') or '-'} / {x.get('ma60_status') or '-'} |",
            f"| 量能/趋势 | {x.get('volume_status') or '-'} / {x.get('trend_status') or '-'} |",
            f"| 风险标签 | {x.get('risk_tags') or '-'} |",
            f"| 交易类型 | {x.get('trade_type') or '-'} |",
            f"| 开仓条件 | 下个交易日若不跌破前一日低点，且结构、量能、板块方向未恶化，则按分组执行；否则不交易。 |",
            f"| 止损条件 | 跌破25日均线或回踩平台低点；若数据无法验证，该交易作废。 |",
            f"| 执行判断 | {x.get('bucket') or '-'} |",
            f"| 逻辑 | {x.get('logic') or '-'} |",
            "",
        ])

    lines.extend([
        "## 【7】可执行交易与淘汰交易",
        "",
        "### 可执行交易（最多3只）",
        "",
    ])
    executable = report.get("executable") or []
    if executable:
        for x in executable:
            lines.append(f"- {x.get('code')} {x.get('name')}：{x.get('logic')}")
    else:
        lines.append("无符合二类/三类买点条件的标的。")

    lines.extend(["", "### 淘汰交易", "", "| 股票 | 淘汰原因 |", "|------|----------|"])
    rejected = report.get("rejected") or []
    if rejected:
        for x in rejected:
            lines.append(f"| {x.get('code','-')} {x.get('name','-')} | {x.get('reject_reason') or x.get('logic') or '-'} |")
    else:
        lines.append("| - | 无 |")

    lines.extend([
        "",
        "## 【10】最终执行建议",
        "",
        "| 项目 | 结论 |",
        "|------|------|",
        f"| 最终策略 | {final.get('strategy','-')} |",
        f"| 是否开新仓 | {final.get('open_new_position','-')} |",
        f"| 可执行交易数量 | {mm.get('executable_count', 0)} |",
        f"| 一句话结论 | {final.get('summary','-')} |",
        "",
        "## 【合规声明】",
        "",
        "本报告依据内部 2560/2568 数据生成，仅用于盘后复盘与下一交易日条件式交易预案；若条件未触发，则不交易。",
        "",
        "**报告结束**",
    ])
    return "\n".join(lines)


def _format_distribution(dist: dict[str, int]) -> str:
    if not dist:
        return "-"
    return " / ".join(f"{k}:{v}" for k, v in sorted(dist.items()))


def _fmt_num(v: Any, digits: int = 2) -> str:
    n = _num(v, default=None)
    if n is None:
        return "-"
    if digits <= 0:
        return str(int(round(n)))
    return f"{n:.{digits}f}"


def _fmt_bool(v: Any) -> str:
    if v is True:
        return "是"
    if v is False:
        return "否"
    return "无法验证"
