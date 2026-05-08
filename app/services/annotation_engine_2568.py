from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class AnnotationConfig2568:
    flat_threshold: float = 0.02
    near_ma25_pct: float = 0.01
    weak_volume_ratio: float = 1.0
    good_volume_ratio: float = 1.2
    strong_volume_ratio: float = 1.5
    acceleration_ratio: float = 1.10
    big_bear_pct: float = -2.0
    pullback_days: int = 7


class AnnotationEngine2568:
    """2568 纯标注 + 亮点总结 + A/B/C/D 分级筛选体系。

    原则：
    - 不打分
    - 不排序
    - 不自动剔除
    - 只输出人工筛选需要看的结构标注、亮点总结、A/B/C/D 分级和人工处理建议
    """

    def __init__(self, db: Session, cfg: AnnotationConfig2568 | None = None):
        self.db = db
        self.cfg = cfg or AnnotationConfig2568()

    @staticmethod
    def market_where(alias: str, market_type: str) -> str:
        mt = (market_type or "all").lower()
        col = f"{alias}.code"
        if mt == "sh":
            return f"{col} LIKE 'sh.%'"
        if mt == "sz":
            return f"{col} LIKE 'sz.%'"
        if mt == "sh60":
            return f"{col} LIKE 'sh.60%'"
        if mt == "sh68":
            return f"{col} LIKE 'sh.68%'"
        if mt == "sz00":
            return f"{col} LIKE 'sz.00%'"
        if mt == "sz30":
            return f"{col} LIKE 'sz.30%'"
        return f"({col} LIKE 'sh.%' OR {col} LIKE 'sz.%')"

    def list_stocks(self, market_type: str, limit: int, q: str | None) -> list[dict[str, Any]]:
        where = [self.market_where("s", market_type)]
        params: dict[str, Any] = {"limit": limit}
        if q:
            where.append("(s.code LIKE :kw OR s.name LIKE :kw)")
            params["kw"] = f"%{q.strip()}%"
        sql = f"""
        SELECT s.code, s.name, s.industry_name, s.board_name, s.source
        FROM stock_info s
        WHERE {' AND '.join(where)}
        ORDER BY s.code
        LIMIT :limit
        """
        return [dict(r) for r in self.db.execute(text(sql), params).mappings().all()]

    def read_latest_indicators(self, codes: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not codes:
            return {}
        params = {f"c{i}": c for i, c in enumerate(codes)}
        clause = "(" + ",".join(f":c{i}" for i in range(len(codes))) + ")"
        sql = f"""
        SELECT t.*
        FROM technical_indicator t
        JOIN (
            SELECT code, date
            FROM (
                SELECT code, date,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
                FROM technical_indicator
                WHERE period='daily' AND code IN {clause}
            ) x
            WHERE rn <= 2
        ) y ON t.code=y.code AND t.date=y.date
        WHERE t.period='daily'
        ORDER BY t.code, t.date DESC
        """
        out: dict[str, list[dict[str, Any]]] = {}
        for r in self.db.execute(text(sql), params).mappings().all():
            out.setdefault(r["code"], []).append(dict(r))
        return out

    def read_recent_daily(self, codes: list[str], days: int = 8) -> dict[str, pd.DataFrame]:
        if not codes:
            return {}
        params = {f"c{i}": c for i, c in enumerate(codes)}
        clause = "(" + ",".join(f":c{i}" for i in range(len(codes))) + ")"
        sql = f"""
        SELECT *
        FROM (
            SELECT code,date,open,high,low,close,volume,amount,source,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
            FROM daily_kline
            WHERE code IN {clause}
        ) x
        WHERE rn <= :days
        ORDER BY code, date
        """
        params["days"] = days
        rows = [dict(r) for r in self.db.execute(text(sql), params).mappings().all()]
        out: dict[str, pd.DataFrame] = {}
        for code in codes:
            df = pd.DataFrame([r for r in rows if r["code"] == code])
            if not df.empty:
                for c in ["open", "high", "low", "close", "volume", "amount"]:
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
            out[code] = df
        return out

    def annotations(
        self,
        market_type: str = "all",
        limit: int = 500,
        q: str | None = None,
        summary: str | None = None,
        risk_only: bool = False,
        manual_action: str | None = None,
        min_a: int | None = None,
        min_b: int | None = None,
        min_d: int | None = None,
    ) -> dict[str, Any]:
        stocks = self.list_stocks(market_type, limit, q)
        codes = [s["code"] for s in stocks]
        ind_map = self.read_latest_indicators(codes)
        recent_map = self.read_recent_daily(codes, days=max(self.cfg.pullback_days + 1, 8))
        items = [
            self.annotate_one(s, ind_map.get(s["code"], []), recent_map.get(s["code"], pd.DataFrame()))
            for s in stocks
        ]

        if summary:
            items = [x for x in items if x.get("summary_label") == summary]
        if risk_only:
            items = [x for x in items if x.get("risk_tags") or x.get("d_count", 0) > 0]
        if manual_action:
            items = [x for x in items if x.get("manual_action_label") == manual_action]
        if min_a is not None:
            items = [x for x in items if int(x.get("a_count") or 0) >= min_a]
        if min_b is not None:
            items = [x for x in items if int(x.get("b_count") or 0) >= min_b]
        if min_d is not None:
            items = [x for x in items if int(x.get("d_count") or 0) >= min_d]

        summary_stats: dict[str, int] = {}
        action_stats: dict[str, int] = {}
        highlight_stats: dict[str, int] = {}
        for x in items:
            label = x.get("summary_label") or "未知"
            action = x.get("manual_action_label") or "未知"
            summary_stats[label] = summary_stats.get(label, 0) + 1
            action_stats[action] = action_stats.get(action, 0) + 1
            for part in (x.get("highlight_summary") or "").split(" / "):
                if part:
                    highlight_stats[part] = highlight_stats.get(part, 0) + 1

        return {
            "summary": {
                "total": len(items),
                "by_label": summary_stats,
                "by_action": action_stats,
                "by_highlight": highlight_stats,
            },
            "items": items,
        }

    def annotate_one(self, stock: dict[str, Any], indicators: list[dict[str, Any]], recent: pd.DataFrame) -> dict[str, Any]:
        code = stock.get("code")
        name = stock.get("name") or ""
        if not indicators:
            row = self._missing_row(code, name)
            row.update(self._highlight_fields(row))
            row.update(self._abcd_fields(row))
            return row

        today = indicators[0]
        yesterday = indicators[1] if len(indicators) > 1 else {}
        close = self._latest_close(recent)
        ma25 = today.get("ma25")
        ma60 = today.get("ma60")
        ma25_y = yesterday.get("ma25")
        ma60_y = yesterday.get("ma60")
        slope25 = today.get("ma25_slope_3")
        slope60 = today.get("ma60_slope_3")
        vol_ma5 = today.get("vol_ma5")
        vol_ma60 = today.get("vol_ma60")
        vol_ratio = today.get("vol_ratio")

        hard_ok = 0
        ma25_status = "✘ MA25 下弯"
        if self._num(ma25) is not None and self._num(ma25_y) is not None and ma25 > ma25_y:
            ma25_status = "✔ MA25 上行"
            hard_ok += 1

        ma60_status = "✘ MA60 下行"
        if self._num(ma60) is not None and self._num(ma60_y) is not None and ma60 >= ma60_y:
            ma60_status = "✔ MA60 上行/走平"
            hard_ok += 1

        price_status = "✘ 跌破 MA25"
        if self._num(close) is not None and self._num(ma25) is not None and close >= ma25:
            price_status = "✔ 站上 MA25"
            hard_ok += 1

        volume_status = "✘ 均量不足"
        if self._num(vol_ma5) is not None and self._num(vol_ma60) is not None and vol_ma5 > vol_ma60:
            volume_status = "✔ 均量放量"
            hard_ok += 1

        trend_status = "✘ 趋势结构弱"
        if self._num(ma25) is not None and self._num(ma60) is not None and ma25 > ma60:
            trend_status = "✔ 趋势结构健康"
            hard_ok += 1

        risks = self._risk_tags(name, recent, close, ma25)
        summary_label = "强满足" if hard_ok >= 4 and not risks else ("临界" if hard_ok >= 3 else "弱满足")

        row = {
            "code": code,
            "name": name,
            "date": today.get("date"),
            "close": close,
            "ma25": ma25,
            "ma60": ma60,
            "vol_ratio": vol_ratio,
            "ma25_status": ma25_status,
            "ma60_status": ma60_status,
            "price_status": price_status,
            "volume_status": volume_status,
            "trend_status": trend_status,
            "slope25_status": self._slope_label(slope25, "MA25", "下弯"),
            "slope60_status": self._slope_label(slope60, "MA60", "下行"),
            "volume_strength_status": self._volume_strength(vol_ratio),
            "kline_position_status": self._kline_position(close, ma25),
            "pullback_status": self._pullback_label(recent, ma25, ma60),
            "risk_tags": " / ".join(risks) if risks else "",
            "summary_label": summary_label,
        }
        row.update(self._highlight_fields(row))
        row.update(self._abcd_fields(row))
        return row

    def _highlight_fields(self, row: dict[str, Any]) -> dict[str, str]:
        trend_highlight = self._trend_highlight(row)
        volume_highlight = self._volume_highlight(row)
        structure_highlight = self._structure_highlight(row)
        safety_highlight = self._safety_highlight(row, trend_highlight)
        risk_highlight = self._risk_highlight(row)
        parts = [trend_highlight, volume_highlight, structure_highlight, safety_highlight]
        if risk_highlight:
            parts.append(risk_highlight)
        return {
            "trend_highlight": trend_highlight,
            "volume_highlight": volume_highlight,
            "structure_highlight": structure_highlight,
            "safety_highlight": safety_highlight,
            "risk_highlight": risk_highlight,
            "highlight_summary": " / ".join([p for p in parts if p]),
        }

    def _abcd_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        a, b, c, d = [], [], [], []

        for key in ["trend_highlight", "volume_highlight", "structure_highlight", "safety_highlight"]:
            v = row.get(key) or ""
            if v in {"⭐ 趋势双线共振", "🔥 强放量", "🟩 结构强", "🟩 回踩确认"}:
                a.append(v)
            elif v in {"🟦 趋势主升段", "⭐ 放量良好", "🟦 结构一般", "🟦 趋势健康"}:
                b.append(v)
            elif v.startswith("~"):
                c.append(v)
            elif v.startswith("⚠") or v.startswith("❌") or v.startswith("✘"):
                d.append(v)

        risk_tags = row.get("risk_tags") or ""
        if risk_tags:
            for r in risk_tags.split(" / "):
                if r and r not in d:
                    d.append(r)
        if "下弯" in (row.get("ma25_status") or ""):
            d.append("⚠ MA25 下弯")
        if "下行" in (row.get("ma60_status") or ""):
            d.append("⚠ MA60 下行")

        # 去重保序
        a = self._unique(a)
        b = self._unique(b)
        c = self._unique(c)
        d = self._unique(d)

        ac, bc, cc, dc = len(a), len(b), len(c), len(d)
        if ac >= 2:
            action = "强势票｜重点关注"
            level = "A2+"
        elif ac >= 1:
            action = "有核心亮点｜可关注"
            level = "A1"
        elif bc >= 3:
            action = "中强票｜观察池"
            level = "B3+"
        elif bc >= 2:
            action = "健康趋势｜可观察"
            level = "B2"
        elif dc >= 3:
            action = "风险较多｜建议移出"
            level = "D3+"
        elif dc == 2:
            action = "风险偏多｜谨慎观察"
            level = "D2"
        elif dc == 1:
            action = "有风险｜人工确认"
            level = "D1"
        else:
            action = "普通结构｜低优先级"
            level = "普通"

        return {
            "a_highlights": " / ".join(a),
            "b_highlights": " / ".join(b),
            "c_highlights": " / ".join(c),
            "d_highlights": " / ".join(d),
            "a_count": ac,
            "b_count": bc,
            "c_count": cc,
            "d_count": dc,
            "highlight_level": level,
            "manual_action_label": action,
        }

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        out = []
        seen = set()
        for item in items:
            if item and item not in seen:
                out.append(item)
                seen.add(item)
        return out

    def _trend_highlight(self, row: dict[str, Any]) -> str:
        ma25 = row.get("ma25_status") or ""
        ma60 = row.get("ma60_status") or ""
        if ma25.startswith("✔") and ma60.startswith("✔"):
            return "⭐ 趋势双线共振"
        if ma25.startswith("✔") and "走平" in ma60:
            return "🟦 趋势健康"
        if "下弯" in ma25 and ma60.startswith("✔"):
            return "⚠ 短期走弱但中期强"
        return "❌ 趋势弱"

    def _volume_highlight(self, row: dict[str, Any]) -> str:
        ratio = self._num(row.get("vol_ratio"))
        if ratio is None:
            return "✘ 缺量比"
        if ratio >= self.cfg.strong_volume_ratio:
            return "🔥 强放量"
        if ratio >= self.cfg.good_volume_ratio:
            return "⭐ 放量良好"
        if ratio >= self.cfg.weak_volume_ratio:
            return "~ 弱放量"
        return "✘ 无放量"

    def _structure_highlight(self, row: dict[str, Any]) -> str:
        close = self._num(row.get("close"))
        ma25 = self._num(row.get("ma25"))
        ma60 = self._num(row.get("ma60"))
        if close is None or ma25 is None or ma60 is None:
            return "✘ 结构不明"
        if ma25 > ma60 and close > ma25:
            return "🟩 结构强"
        if close > ma25:
            return "🟦 结构一般"
        if close < ma25:
            return "⚠ 结构破位"
        return "✘ 结构不明"

    def _safety_highlight(self, row: dict[str, Any], trend_highlight: str) -> str:
        risk = row.get("risk_tags") or ""
        pullback = row.get("pullback_status") or ""
        if pullback.startswith("✔"):
            return "🟩 回踩确认"
        if "跌破 MA25" in risk:
            return "⚠ 跌破 MA25"
        if trend_highlight in {"⭐ 趋势双线共振", "🟦 趋势健康"}:
            return "🟦 趋势主升段"
        return "~ 安全结构一般"

    def _risk_highlight(self, row: dict[str, Any]) -> str:
        risks = []
        risk_tags = row.get("risk_tags") or ""
        if risk_tags:
            risks.append(risk_tags)
        if "下弯" in (row.get("ma25_status") or ""):
            risks.append("⚠ 短期走弱")
        if "下行" in (row.get("ma60_status") or ""):
            risks.append("⚠ 中期走弱")
        return " / ".join([r for r in risks if r])

    @staticmethod
    def _missing_row(code, name):
        return {
            "code": code,
            "name": name,
            "date": None,
            "close": None,
            "ma25": None,
            "ma60": None,
            "vol_ratio": None,
            "ma25_status": "✘ 缺 MA25 指标",
            "ma60_status": "✘ 缺 MA60 指标",
            "price_status": "✘ 缺价格/指标",
            "volume_status": "✘ 缺量能指标",
            "trend_status": "✘ 缺趋势结构",
            "slope25_status": "✘ 缺 MA25 斜率",
            "slope60_status": "✘ 缺 MA60 斜率",
            "volume_strength_status": "✘ 缺量比",
            "kline_position_status": "✘ 缺价格位置",
            "pullback_status": "~ 无明显回踩",
            "risk_tags": "⚠ 数据不足",
            "summary_label": "弱满足",
        }

    @staticmethod
    def _num(v):
        try:
            if v is None or pd.isna(v):
                return None
            return float(v)
        except Exception:
            return None

    @staticmethod
    def _latest_close(df: pd.DataFrame):
        if df is None or df.empty or "close" not in df.columns:
            return None
        return float(df.sort_values("date").iloc[-1]["close"])

    def _slope_label(self, value, name: str, neg_word: str) -> str:
        v = self._num(value)
        if v is None:
            return f"✘ 缺 {name} 斜率"
        if v > self.cfg.flat_threshold:
            return f"✔ {name} 斜率正"
        if abs(v) <= self.cfg.flat_threshold:
            return f"~ {name} 走平"
        return f"✘ {name} {neg_word}"

    def _volume_strength(self, ratio) -> str:
        v = self._num(ratio)
        if v is None:
            return "✘ 缺量比"
        if v > self.cfg.good_volume_ratio:
            return "✔ 放量良好"
        if v > self.cfg.weak_volume_ratio:
            return "~ 弱放量"
        return "✘ 无放量"

    def _kline_position(self, close, ma25) -> str:
        c = self._num(close)
        m = self._num(ma25)
        if c is None or m is None or m == 0:
            return "✘ 缺价格位置"
        if c > m:
            return "✔ 在趋势线上方"
        if abs(c - m) / m <= self.cfg.near_ma25_pct:
            return "~ 贴着 MA25"
        return "✘ 跌破 MA25"

    def _pullback_label(self, recent: pd.DataFrame, ma25, ma60) -> str:
        m25 = self._num(ma25)
        m60 = self._num(ma60)
        if recent is None or recent.empty or m25 is None or m60 is None:
            return "~ 无明显回踩"
        tail = recent.sort_values("date").tail(self.cfg.pullback_days)
        low = float(tail["low"].min()) if "low" in tail else None
        if low is not None and low <= m25 and low >= m60:
            return "✔ 回踩确认"
        return "~ 无明显回踩"

    def _risk_tags(self, name: str, recent: pd.DataFrame, close, ma25) -> list[str]:
        risks: list[str] = []
        if "ST" in (name or "").upper():
            risks.append("⚠ ST 风险")
        if recent is not None and not recent.empty:
            df = recent.sort_values("date")
            if len(df) >= 3:
                vols = list(df.tail(3)["volume"])
                if vols[2] < vols[1] < vols[0]:
                    risks.append("⚠ 连续缩量")
            if len(df) >= 2:
                last = df.iloc[-1]
                prev = df.iloc[-2]
                if prev.get("close") and prev["close"] != 0:
                    pct = (last["close"] - prev["close"]) / prev["close"] * 100
                    if self._num(ma25) is not None and last["close"] < ma25 and pct <= self.cfg.big_bear_pct:
                        risks.append("⚠ 跌破 MA25（大阴）")
        c = self._num(close)
        m = self._num(ma25)
        if c is not None and m is not None and m != 0 and c / m > self.cfg.acceleration_ratio:
            risks.append("⚠ 加速段（非买点）")
        return risks
