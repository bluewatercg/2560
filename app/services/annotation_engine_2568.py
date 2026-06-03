from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.market_scope import market_sql_where
from app.db.clickhouse import get_clickhouse


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
        return market_sql_where(f"{alias}.code", market_type)

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
        ch = get_clickhouse()
        code_list = ",".join(f"'{c}'" for c in codes)
        sql = f"""
        SELECT t.*
        FROM technical_indicator t
        JOIN (
            SELECT code, date
            FROM (
                SELECT code, date,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) AS rn
                FROM technical_indicator
                WHERE period='daily' AND code IN ({code_list})
            ) x
            WHERE rn <= 2
        ) y ON t.code=y.code AND t.date=y.date
        WHERE t.period='daily'
        ORDER BY t.code, t.date DESC
        """
        out: dict[str, list[dict[str, Any]]] = {}
        for r in ch.query(sql):
            d = self._to_int_date(r.get("date"))
            if d and d >= 19900101:
                out.setdefault(r["code"], []).append(dict(r))
        return out

    def build_daily_indicators_from_kline(self, codes: list[str], days: int = 80) -> dict[str, list[dict[str, Any]]]:
        if not codes:
            return {}
        out: dict[str, list[dict[str, Any]]] = {}
        ch = get_clickhouse()
        for code in codes:
            rows = ch.query(
                f"""
                SELECT code,date,open,high,low,close,volume,amount,source
                FROM daily_kline
                WHERE code='{code}'
                ORDER BY date DESC
                LIMIT {days}
                """
            )
            if not rows:
                continue
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close", "volume", "amount"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.sort_values("date").reset_index(drop=True)
            df["ma25"] = df["close"].rolling(25, min_periods=1).mean()
            df["ma60"] = df["close"].rolling(60, min_periods=1).mean()
            df["ma25_slope_3"] = (df["ma25"] - df["ma25"].shift(3)) / df["ma25"].shift(3).replace(0, pd.NA) * 100
            df["ma60_slope_3"] = (df["ma60"] - df["ma60"].shift(3)) / df["ma60"].shift(3).replace(0, pd.NA) * 100
            df["vol_ma5"] = df["volume"].rolling(5, min_periods=1).mean()
            df["vol_ma60"] = df["volume"].rolling(60, min_periods=1).mean()
            df["vol_ratio"] = df["vol_ma5"] / df["vol_ma60"].replace(0, pd.NA)
            latest = df.tail(2).iloc[::-1]
            out[code] = [
                {
                    "code": code,
                    "period": "daily",
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "close": None if pd.isna(row["close"]) else float(row["close"]),
                    "ma25": None if pd.isna(row["ma25"]) else float(row["ma25"]),
                    "ma60": None if pd.isna(row["ma60"]) else float(row["ma60"]),
                    "ma25_slope_3": None if pd.isna(row["ma25_slope_3"]) else float(row["ma25_slope_3"]),
                    "ma60_slope_3": None if pd.isna(row["ma60_slope_3"]) else float(row["ma60_slope_3"]),
                    "vol_ma5": None if pd.isna(row["vol_ma5"]) else float(row["vol_ma5"]),
                    "vol_ma60": None if pd.isna(row["vol_ma60"]) else float(row["vol_ma60"]),
                    "vol_ratio": None if pd.isna(row["vol_ratio"]) else float(row["vol_ratio"]),
                    "source": "daily_kline_dynamic",
                    "updated_at": None,
                }
                for _, row in latest.iterrows()
            ]
        return out

    def latest_daily_indicator_date(self, market_type: str) -> int | None:
        where = market_sql_where("code", market_type)
        row = get_clickhouse().query_one(
            f"SELECT max(date) AS latest_date FROM technical_indicator WHERE period='daily' AND {where} AND date >= toDate('1990-01-01')"
        )
        if row and row.get("latest_date"):
            d = pd.to_datetime(row["latest_date"])
            return int(d.strftime("%Y%m%d"))
        row = get_clickhouse().query_one(
            f"SELECT max(date) AS latest_date FROM daily_kline WHERE {where}"
        )
        if row and row.get("latest_date"):
            d = pd.to_datetime(row["latest_date"])
            return int(d.strftime("%Y%m%d"))
        return None

    def latest_2560_batch(self) -> dict[str, Any] | None:
        row = self.db.execute(text("""
            SELECT batch_id, run_time
            FROM analysis_batch
            WHERE strategy_code='S2560' AND status='success'
            ORDER BY run_time DESC
            LIMIT 1
        """)).mappings().first()
        return dict(row) if row else None

    def latest_2560_signals(self, codes: list[str], batch_id: int | None) -> dict[str, dict[str, Any]]:
        if not codes or not batch_id:
            return {}
        params: dict[str, Any] = {"batch_id": batch_id}
        params.update({f"c{i}": c for i, c in enumerate(codes)})
        clause = "(" + ",".join(f":c{i}" for i in range(len(codes))) + ")"
        sql = f"""
            SELECT code, batch_id, signal_time
            FROM structure_2560_analysis
            WHERE batch_id=:batch_id
              AND code IN {clause}
              AND selected_signal=1
        """
        return {
            r["code"]: dict(r)
            for r in self.db.execute(text(sql), params).mappings().all()
        }

    def read_recent_daily(self, codes: list[str], days: int = 8) -> dict[str, pd.DataFrame]:
        if not codes:
            return {}
        out: dict[str, pd.DataFrame] = {}
        for code in codes:
            rows = get_clickhouse().query(
                f"SELECT code,date,open,high,low,close,volume,amount,source FROM daily_kline WHERE code='{code}' ORDER BY date DESC LIMIT {days}"
            )
            if not rows:
                out[code] = pd.DataFrame()
                continue
            df = pd.DataFrame(rows)
            # Convert ClickHouse Date strings to int YYYYMMDD
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d').astype(int)
            for c in ["open", "high", "low", "close", "volume", "amount"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.sort_values(["date"]).reset_index(drop=True)
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
        missing_indicator_codes = [c for c in codes if not self._has_usable_indicator(ind_map.get(c))]
        if missing_indicator_codes:
            ind_map.update(self.build_daily_indicators_from_kline(missing_indicator_codes))
        recent_map = self.read_recent_daily(codes, days=max(self.cfg.pullback_days + 1, 8))
        latest_indicator_date = self.latest_daily_indicator_date(market_type)
        latest_batch = self.latest_2560_batch()
        latest_signals = self.latest_2560_signals(
            codes,
            int(latest_batch["batch_id"]) if latest_batch and latest_batch.get("batch_id") is not None else None,
        )
        items = [
            self.annotate_one(
                s,
                ind_map.get(s["code"], []),
                recent_map.get(s["code"], pd.DataFrame()),
                latest_indicator_date=latest_indicator_date,
                latest_signal=latest_signals.get(s["code"]),
                latest_batch=latest_batch,
            )
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

    def annotations_for_codes(self, codes: list[str]) -> dict[str, Any]:
        ordered_codes = []
        seen = set()
        for code in codes:
            c = (code or "").strip()
            if c and c not in seen:
                ordered_codes.append(c)
                seen.add(c)
        if not ordered_codes:
            return {"summary": {"total": 0, "by_label": {}, "by_action": {}, "by_highlight": {}}, "items": []}

        stmt = text("""
            SELECT code, name, industry_name, board_name, source
            FROM stock_info
            WHERE code IN :codes
        """).bindparams(bindparam("codes", expanding=True))
        stock_map = {
            r["code"]: dict(r)
            for r in self.db.execute(stmt, {"codes": ordered_codes}).mappings().all()
        }
        stocks = [
            stock_map.get(code) or {"code": code, "name": "", "industry_name": None, "board_name": None, "source": None}
            for code in ordered_codes
        ]
        ind_map = self.read_latest_indicators(ordered_codes)
        missing_indicator_codes = [c for c in ordered_codes if not self._has_usable_indicator(ind_map.get(c))]
        if missing_indicator_codes:
            ind_map.update(self.build_daily_indicators_from_kline(missing_indicator_codes))
        recent_map = self.read_recent_daily(ordered_codes, days=max(self.cfg.pullback_days + 1, 8))
        latest_indicator_date = None
        try:
            latest_indicator_date = self.latest_daily_indicator_date("all")
        except Exception:
            latest_indicator_date = None
        latest_batch = self.latest_2560_batch()
        latest_batch_id = latest_batch.get("batch_id") if latest_batch else None
        try:
            latest_batch_id = int(latest_batch_id) if latest_batch_id is not None else None
        except Exception:
            latest_batch_id = None
        latest_signals = self.latest_2560_signals(
            ordered_codes,
            latest_batch_id,
        )
        items = [
            self.annotate_one(
                s,
                ind_map.get(s["code"], []),
                recent_map.get(s["code"], pd.DataFrame()),
                latest_indicator_date=latest_indicator_date,
                latest_signal=latest_signals.get(s["code"]),
                latest_batch=latest_batch,
            )
            for s in stocks
        ]
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

    def annotate_one(
        self,
        stock: dict[str, Any],
        indicators: list[dict[str, Any]],
        recent: pd.DataFrame,
        latest_indicator_date: int | None = None,
        latest_signal: dict[str, Any] | None = None,
        latest_batch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        code = stock.get("code")
        name = stock.get("name") or ""
        if not indicators:
            row = self._missing_row(code, name)
            row.update(self._freshness_fields(None, latest_indicator_date, latest_signal, latest_batch))
            row.update(self._highlight_fields(row))
            row.update(self._abcd_fields(row))
            return row

        today = indicators[0]
        yesterday = indicators[1] if len(indicators) > 1 else {}
        close = self._latest_close(recent)
        volume = self._latest_value(recent, "volume")
        amount = self._latest_value(recent, "amount")
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
            "volume": volume,
            "amount": amount,
            "ma25": ma25,
            "ma60": ma60,
            "ma25_direction": self._direction_label(ma25, ma25_y),
            "ma60_direction": self._direction_label(ma60, ma60_y),
            "price_ma25_deviation_pct": today.get("price_ma25_deviation_pct"),
            "vol_ma5": vol_ma5,
            "vol_ma60": vol_ma60,
            "vol_ma5_gt_vol_ma60": (
                bool(vol_ma5 > vol_ma60)
                if self._num(vol_ma5) is not None and self._num(vol_ma60) is not None
                else None
            ),
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
        row.update(self._freshness_fields(today, latest_indicator_date, latest_signal, latest_batch))
        row.update(self._highlight_fields(row))
        row.update(self._abcd_fields(row))
        return row

    @staticmethod
    def _to_int_date(v) -> int | None:
        """Convert date value (int, date string, datetime string) to YYYYMMDD int."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        if not s:
            return None
        # Handle datetime strings like '1970-01-01 05:37:40.519' or '2026-05-18T15:00:00'
        try:
            return int(pd.to_datetime(s).strftime("%Y%m%d"))
        except Exception:
            pass
        # Handle pure numeric strings like '20260518'
        if s.isdigit():
            return int(s[:8])
        return None

    @staticmethod
    def _has_usable_indicator(rows: list[dict[str, Any]] | None) -> bool:
        if not rows:
            return False
        latest = rows[0]
        required = ("ma25", "ma60", "vol_ma5", "vol_ma60")
        return any(AnnotationEngine2568._num(latest.get(k)) is not None for k in required)

    @staticmethod
    def _freshness_fields(
        indicator: dict[str, Any] | None,
        latest_indicator_date: int | None,
        latest_signal: dict[str, Any] | None,
        latest_batch: dict[str, Any] | None,
    ) -> dict[str, Any]:
        indicator_date = AnnotationEngine2568._to_int_date(indicator.get("date") if indicator else None)
        indicator_updated_at = indicator.get("updated_at") if indicator else None
        updated_at_date = AnnotationEngine2568._to_int_date(indicator_updated_at)
        if updated_at_date is not None and updated_at_date < 19900101:
            indicator_updated_at = None
        if indicator_date is None:
            indicator_status = "缺指标"
        elif latest_indicator_date is not None and indicator_date >= latest_indicator_date:
            indicator_status = "已重算"
        else:
            indicator_status = "未更新到最新"

        latest_batch_id = latest_batch.get("batch_id") if latest_batch else None
        latest_run_time = latest_batch.get("run_time") if latest_batch else None
        if latest_signal:
            latest_2560_status = "命中"
            signal_time = latest_signal.get("signal_time")
        elif latest_batch:
            latest_2560_status = "未命中"
            signal_time = None
        else:
            latest_2560_status = "未计算"
            signal_time = None

        return {
            "indicator_freshness_status": indicator_status,
            "indicator_date": indicator_date,
            "latest_indicator_date": latest_indicator_date,
            "indicator_recalculated_at": indicator_updated_at,
            "latest_2560_status": latest_2560_status,
            "latest_2560_batch_id": latest_batch_id,
            "latest_2560_run_time": latest_run_time,
            "latest_2560_signal_time": signal_time,
        }

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

    @staticmethod
    def _latest_value(df: pd.DataFrame, column: str):
        if df is None or df.empty or column not in df.columns:
            return None
        v = df.sort_values("date").iloc[-1][column]
        try:
            if pd.isna(v):
                return None
            return float(v)
        except Exception:
            return None

    @staticmethod
    def _direction_label(current, previous) -> str:
        c = AnnotationEngine2568._num(current)
        p = AnnotationEngine2568._num(previous)
        if c is None or p is None or p == 0:
            return "无法验证"
        pct = (c - p) / abs(p) * 100
        if pct > 0.05:
            return "向上"
        if pct < -0.05:
            return "向下"
        return "走平"

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
