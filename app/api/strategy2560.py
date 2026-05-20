from datetime import date, timedelta
import json
import time
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.core.market_scope import market_sql_where
from app.db.clickhouse import get_clickhouse
from app.services.data_freshness_service import can_run_2560, classify_gap
from app.services.signal_engine_2560 import SignalEngine2560
from app.services.statistics_engine import StatisticsEngine
from app.services.strategy2560_service import Strategy2560Service

router = APIRouter(prefix='/api/strategy/2560', tags=['strategy-2560'])

SUPPORTED_TYPES = {
    'sz00': ('sz.', '00', '深市00'),
    'sz30': ('sz.', '30', '创业板30'),
    'sh60': ('sh.', '60', '沪市60'),
    'sh68': ('sh.', '68', '科创板68'),
}
NORMALIZED_CODE_SQL = (
    "CASE "
    "WHEN LOWER(code) LIKE 'sz.%' OR LOWER(code) LIKE 'sh.%' THEN SUBSTRING(code, 4) "
    "WHEN LOWER(code) LIKE 'sz%' OR LOWER(code) LIKE 'sh%' THEN SUBSTRING(code, 3) "
    "ELSE code END"
)

def normalize_code(raw: str | None) -> str:
    if raw is None:
        return ''
    s = str(raw).strip().lower().replace('-', '').replace('_', '')
    if s.startswith('sz.') or s.startswith('sh.'):
        s = s[3:]
    elif s.startswith('sz') or s.startswith('sh'):
        s = s[2:]
    digits = ''.join(ch for ch in s if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits

def type_key_for_code(code: str) -> str | None:
    c = normalize_code(code)
    if c.startswith('00'):
        return 'sz00'
    if c.startswith('30'):
        return 'sz30'
    if c.startswith('60'):
        return 'sh60'
    if c.startswith('68'):
        return 'sh68'
    return None

def market_code(code: str) -> str:
    c = normalize_code(code)
    t = type_key_for_code(c)
    return SUPPORTED_TYPES[t][0] + c if t else code

def board_type(code: str) -> str:
    t = type_key_for_code(code)
    return SUPPORTED_TYPES[t][2] if t else '其他'

def is_supported_code(code: str) -> bool:
    return type_key_for_code(code) is not None

def supported_sql_where() -> str:
    n = NORMALIZED_CODE_SQL
    return f"({n} LIKE '00%' OR {n} LIKE '30%' OR {n} LIKE '60%' OR {n} LIKE '68%')"

def type_sql_where(type_key: str) -> str:
    n = NORMALIZED_CODE_SQL
    type_key = (type_key or 'all').lower().strip()
    if type_key in SUPPORTED_TYPES:
        return f"{n} LIKE '{SUPPORTED_TYPES[type_key][1]}%'"
    if type_key == 'sz':
        return f"({n} LIKE '00%' OR {n} LIKE '30%')"
    if type_key == 'sh':
        return f"({n} LIKE '60%' OR {n} LIKE '68%')"
    return supported_sql_where()

def market_type_matches(code: str, market_type: str) -> bool:
    t = type_key_for_code(code)
    mt = (market_type or 'all').lower().strip()
    return mt in ('', 'all') or mt == t or (mt == 'sz' and t in ('sz00', 'sz30')) or (mt == 'sh' and t in ('sh60', 'sh68'))

def resolve_db_code(db: Session, raw_code: str, market_type: str = 'all') -> str | None:
    raw = (raw_code or '').strip()
    norm = normalize_code(raw)
    if not norm or not is_supported_code(norm) or not market_type_matches(norm, market_type):
        return None
    candidates = [raw, norm, 'sz' + norm, 'sh' + norm, 'sz.' + norm, 'sh.' + norm]
    sql = (
        f"SELECT code FROM stock_info WHERE ({NORMALIZED_CODE_SQL}=:norm OR code IN :candidates) "
        f"AND {type_sql_where(market_type)} ORDER BY code LIMIT 1"
    )
    rows = db.execute(text(sql), {'norm': norm, 'candidates': tuple(candidates)}).fetchall()
    return rows[0][0] if rows else None

def in_clause(values: list[str], prefix: str = 'c') -> tuple[str, dict]:
    params = {f'{prefix}{i}': v for i, v in enumerate(values)}
    clause = '(' + ','.join(f':{prefix}{i}' for i in range(len(values))) + ')'
    return clause, params

class RunAnalysisRequest(BaseModel):
    codes: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=10000)
    rebuild_statistics: bool = True
    market_type: Optional[str] = Field(default='all')

MARKETS = ["sh60", "sh68", "sz00", "sz30"]


def _table_exists(db: Session, table_name: str) -> bool:
    return bool(
        db.execute(
            text("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name=:t
            """),
            {"t": table_name},
        ).scalar()
        or 0
    )


def _market_latest_indicator(db: Session, market: str, period: str) -> int | None:
    """Return latest date for technical_indicator of a market+period, or None."""
    # technical_indicator 现在存储在 ClickHouse
    where = market_sql_where("code", market)
    row = get_clickhouse().query_one(
        f"SELECT max(date) AS d FROM technical_indicator WHERE {where} AND period='{period}'"
    )
    if not row or not row.get("d"):
        return None
    d = pd.to_datetime(row["d"])
    return int(d.strftime("%Y%m%d%H%M%S")) if period != "daily" else int(d.strftime("%Y%m%d"))


def _market_latest_kline(db: Session, market: str, period: str) -> int | None:
    """Return the latest date integer (YYYYMMDD or YYYYMMDDHHMMSS) for a market+period, or None."""
    table = "minute_kline_period" if period != "daily" else "daily_kline"
    where = market_sql_where("code", market)
    extra = f" AND period='{period}'" if period != "daily" else ""
    row = get_clickhouse().query_one(
        f"SELECT max(date) AS d FROM {table} WHERE {where}{extra}"
    )
    if not row or not row.get("d"):
        return None
    d = pd.to_datetime(row["d"])
    return int(d.strftime("%Y%m%d%H%M%S")) if period != "daily" else int(d.strftime("%Y%m%d"))


def _market_source_latest(db: Session, market: str) -> int | None:
    """Read latest date from data_import_batch for a market's import."""
    if not _table_exists(db, "data_import_batch"):
        return None
    row = db.execute(
        text("""
            SELECT MAX(b.finished_at) AS finished
            FROM data_import_batch b
            WHERE b.market=:m AND b.status='success'
        """),
        {"m": market},
    ).mappings().first()
    if not row or not row.get("finished"):
        return None
    # Use latest successful batch's end date via data_import_file
    batch_id = db.execute(
        text("""
            SELECT id FROM data_import_batch
            WHERE market=:m AND status='success'
            ORDER BY id DESC LIMIT 1
        """),
        {"m": market},
    ).scalar()
    if not batch_id:
        return None
    # Get max date from the imported files
    table = "daily_kline"
    files = db.execute(
        text("""
            SELECT file_path FROM data_import_file
            WHERE import_batch_id=:bid AND status='success'
            LIMIT 200
        """),
        {"bid": batch_id},
    ).mappings().all()
    codes = []
    import os
    for f in files:
        stem = os.path.basename(str(f["file_path"])).split(".")[0].lower()
        digits = "".join(ch for ch in stem if ch.isdigit())
        if len(digits) >= 6:
            codes.append(f"{digits[-6:]}")
    if not codes:
        return None
    codes_str = ",".join(f"'{c}'" for c in codes)
    r = get_clickhouse().query_one(
        f"SELECT MAX(date) AS d FROM daily_kline WHERE code IN ({codes_str})"
    )
    if not r or not r.get("d"):
        return None
    return int(pd.to_datetime(r["d"]).strftime("%Y%m%d"))


def _zero_hit_explain(db: Session, today_int: int, funnel_summary: dict) -> dict:
    """0 命中分三档解释：单日 0 / 连续 3-5 日 / 连续 10 日。"""
    MARKETS_LIST = ["sh60", "sh68", "sz00", "sz30"]

    # 先看当前漏斗：A 层是否已有命中
    current_a = sum(
        int((funnel_summary.get(m, {}).get("tiers", {}).get("A", {}) or {}).get("count") or 0)
        for m in MARKETS_LIST
    )
    if current_a > 0:
        return {
            "level": "normal",
            "title": f"当前严格结构 A 层 {current_a} 只",
            "detail": "当前漏斗已有 A 层严格结构，0 命中解释不触发。",
            "severity": "ok",
        }

    # A 层当前为 0，查历史批次看连续天数
    rows = db.execute(text("""
        SELECT batch_id, run_time, status, message
        FROM analysis_batch
        WHERE strategy_code = 'S2560'
          AND status = 'success'
        ORDER BY run_time DESC
        LIMIT 80
    """)).mappings().all()

    # 按天分组
    daily_signals = {}
    for r in rows:
        msg = str(r.get("message") or "")
        sig_count = 0
        for part in msg.split(", "):
            if part.strip().startswith("signals="):
                try:
                    sig_count = int(part.strip().split("=")[1])
                except (ValueError, IndexError):
                    pass
        run_time = r.get("run_time")
        if run_time:
            day_int = int(run_time.strftime("%Y%m%d"))
        else:
            day_int = 0
        if day_int not in daily_signals:
            daily_signals[day_int] = 0
        daily_signals[day_int] += sig_count

    sorted_days = sorted(daily_signals.keys(), reverse=True)
    if not sorted_days:
        return {
            "level": "unknown",
            "title": "无历史运行记录",
            "detail": "尚未运行过 2560，请先完成数据准备并运行一次。",
            "severity": "info",
        }

    # 检查最近运行日是否有信号产出
    most_recent_day = max(sorted_days)
    most_recent_signals = daily_signals[most_recent_day]

    # 从最近运行日开始往前数 0 信号天数
    zero_streak = 0
    if most_recent_signals == 0:
        for day in sorted_days:
            if daily_signals.get(day, 0) == 0:
                zero_streak += 1
            else:
                break

    if zero_streak >= 10:
        return {
            "level": "critical",
            "title": f"连续 {zero_streak} 日严格结构为 0 — 口径异常",
            "detail": "已连续 10 个交易日以上四市场 A 层为 0，必须检查：数据范围是否完整、指标是否重算、信号落库是否正常、漏斗卡点是否异常。",
            "severity": "error",
            "streak": zero_streak,
        }
    elif zero_streak >= 3:
        # 找出漏斗最大卡点
        bottlenecks = {}
        for mkt in MARKETS_LIST:
            if mkt in funnel_summary:
                b = funnel_summary[mkt].get("bottleneck")
                if b:
                    bottlenecks[mkt] = b
        bn_text = "、".join(f"{m}: {b}" for m, b in bottlenecks.items()) if bottlenecks else ""
        return {
            "level": "warning",
            "title": f"连续 {zero_streak} 日严格结构为 0 — 算法诊断",
            "detail": f"连续 3-5 个交易日四市场 A 层为 0。重点看漏斗卡点：{bn_text}。可能原因：市场趋势弱、量能结构不支持、或算法口径偏严。",
            "severity": "warn",
            "streak": zero_streak,
            "bottlenecks": bottlenecks,
        }
    elif zero_streak >= 1:
        return {
            "level": "normal",
            "title": "单日严格结构为 0 — 正常",
            "detail": "市场高位冲刺、快速轮动、个股离 MA25 太远，或 30m 未给右侧确认。A 层本来就允许经常为 0。",
            "severity": "ok",
            "streak": zero_streak,
        }
    else:
        return {
            "level": "normal",
            "title": "当前严格结构 A 层为 0，历史未形成连续 0",
            "detail": "当前漏斗 A 层为 0，但最近成功运行日有信号产出，暂不判定为连续 0 命中异常。请以当前漏斗卡点和 B/C 观察池为主。",
            "severity": "ok",
            "streak": 0,
        }



_workspace_cache = {"data": None, "ts": 0, "ttl": 10}


@router.get("/workspace", response_model=ApiResponse)
def workspace(db: Session = Depends(get_db)):
    """今日工作台：从 workspace_status 预计算表读取，不做实时 MAX() 聚合。"""
    now = time.time()
    if _workspace_cache["data"] and (now - _workspace_cache["ts"]) < _workspace_cache["ttl"]:
        return _workspace_cache["data"]

    today = date.today()
    today_int = int(today.strftime("%Y%m%d"))

    # 1. 四市场就绪状态 — 直接从 workspace_status 小表读取
    from app.services.workspace_service import ensure_workspace_table, refresh_market_from_db
    created = ensure_workspace_table(db)
    if created:
        # 首次建表，做一次真实 MAX() 扫描初始化
        for m in MARKETS:
            refresh_market_from_db(db, m, periods=None)

    rows = db.execute(text("""
        SELECT market, daily_latest, k5m_latest, k30m_latest,
               ind_daily, ind_5m, ind_30m,
               indicators_fresh, ready, missing_json,
               status_text, daily_gap_label, daily_gap
        FROM workspace_status ORDER BY market
    """)).mappings().all()

    market_readiness = []
    for r in rows:
        d = dict(r)
        # missing JSON → 中文列表
        missing_raw = d.pop("missing_json", None)
        if isinstance(missing_raw, str):
            try:
                missing_raw = json.loads(missing_raw)
            except json.JSONDecodeError:
                missing_raw = []
        if not isinstance(missing_raw, list):
            missing_raw = []
        label_map = {"daily": "日线", "5m": "5m", "30m": "30m"}
        d["missing"] = [label_map.get(x, x) for x in missing_raw]
        d["status"] = d.pop("status_text", "")
        d["indicators_fresh"] = bool(d.get("indicators_fresh", 0))
        d["ready"] = bool(d.get("ready", 0))
        market_readiness.append(d)

    # 补齐可能缺失的市场（空行）
    existing = {mr["market"] for mr in market_readiness}
    for mkt in MARKETS:
        if mkt not in existing:
            market_readiness.append({
                "market": mkt, "daily_latest": None, "k5m_latest": None,
                "k30m_latest": None, "ready": False, "status": "数据不足",
                "missing": ["日线", "5m", "30m"], "daily_gap_label": "",
                "daily_gap": None, "indicators_fresh": False,
            })

    # 2. 下一步建议（纯内存计算）
    suggestions = []
    for mr in market_readiness:
        if not mr["ready"]:
            if mr["missing"]:
                missing_str = "、".join(mr["missing"])
                suggestions.append(
                    {
                        "market": mr["market"],
                        "action": "导入数据",
                        "reason": f"缺{missing_str}数据",
                        "view": "data-update",
                        "priority": 1,
                    }
                )
            elif not mr.get("indicators_fresh", True):
                suggestions.append(
                    {
                        "market": mr["market"],
                        "action": "重算指标",
                        "reason": "数据已导入但指标未更新",
                        "view": "data-import-batches",
                        "priority": 2,
                    }
                )
    ready_markets = [mr["market"] for mr in market_readiness if mr["ready"]]
    if ready_markets:
        suggestions.append(
            {
                "market": "、".join(ready_markets),
                "action": "运行2560",
                "reason": f"{len(ready_markets)}个市场可跑",
                "view": "jobs",
                "priority": 3,
            }
        )
    suggestions.sort(key=lambda x: x["priority"])

    # 3. 正在运行的 2560 任务
    running_jobs = []
    if _table_exists(db, "job_execution"):
        rows = db.execute(
            text("""
                SELECT id, job_type, market, status, progress_current, progress_total,
                       success_count, failed_count, message, started_at
                FROM job_execution
                WHERE job_type IN ('run_2560', 'run_2560_now')
                  AND status IN ('running', 'queued', 'pending')
                ORDER BY id
            """),
        ).mappings().all()
        for r in rows:
            d = dict(r)
            d["progress_percent"] = (
                round(int(d.get("progress_current") or 0) * 100 / int(d.get("progress_total") or 1), 1)
                if d.get("progress_total")
                else 0
            )
            running_jobs.append(d)

    # 4. 观察池摘要（top 10 A/B 级）
    observation_pool = []
    try:
        from app.services.annotation_engine_2568 import AnnotationEngine2568

        ann = AnnotationEngine2568(db).annotations(
            market_type="all", limit=10, min_a=0, min_b=2
        )
        items = ann.get("items", [])[:10]
        for it in items:
            observation_pool.append(
                {
                    "code": it.get("code"),
                    "name": it.get("name"),
                    "highlight_level": it.get("highlight_level"),
                    "manual_action_label": it.get("manual_action_label"),
                    "highlight_summary": it.get("highlight_summary"),
                    "a_count": it.get("a_count"),
                    "b_count": it.get("b_count"),
                    "d_count": it.get("d_count"),
                    "ma25_status": it.get("ma25_status"),
                    "trend_status": it.get("trend_status"),
                    "latest_2560_status": it.get("latest_2560_status"),
                }
            )
    except Exception:
        pass

    # 5. 漏斗摘要（有数据的市场计算）
    funnel_summary = {}
    for mr in market_readiness:
        if mr.get("daily_latest") and mr.get("k30m_latest"):
            try:
                funnel_summary[mr["market"]] = _compute_funnel(db, mr["market"])
            except Exception:
                pass

    # 6. 0 命中解释口径
    zero_hit_explain = _zero_hit_explain(db, today_int, funnel_summary)

    result = ApiResponse(
        data={
            "target_date": today.strftime("%Y-%m-%d"),
            "target_date_int": today_int,
            "market_readiness": market_readiness,
            "suggestions": suggestions,
            "running_jobs": running_jobs,
            "observation_pool": observation_pool,
            "funnel_summary": funnel_summary,
            "zero_hit_explain": zero_hit_explain,
        }
    )
    _workspace_cache["data"] = result
    _workspace_cache["ts"] = time.time()
    return result


@router.get("/overview", response_model=ApiResponse)
def overview(db: Session = Depends(get_db)):
    return ApiResponse(data=Strategy2560Service(db).overview())

@router.get('/stocks', response_model=ApiResponse)
def stocks(q: Optional[str] = None, market_type: Optional[str] = Query(default='all'), limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    mt = (market_type or 'all').lower().strip()
    where = [supported_sql_where()]
    if mt != 'all':
        where.append(type_sql_where(mt))
    params = {'limit': limit}
    q_norm = (q or '').strip().lower()
    q_code = normalize_code(q_norm)
    if q_norm:
        where.append(f"({NORMALIZED_CODE_SQL} LIKE :kw_norm OR LOWER(code) LIKE :kw_raw OR name LIKE :kw_raw OR {NORMALIZED_CODE_SQL}=:exact_code)")
        params.update({'kw_norm': f'%{q_code or q_norm}%', 'kw_raw': f'%{q_norm}%', 'exact_code': q_code or q_norm})
    sql = f"SELECT code,{NORMALIZED_CODE_SQL} AS normalized_code,name,industry_name,board_name,source FROM stock_info WHERE {' AND '.join(where)} ORDER BY normalized_code LIMIT :limit"
    rows = db.execute(text(sql), params).mappings().all()
    data = []
    for r in rows:
        item = dict(r)
        normalized = item.get('normalized_code') or item['code']
        item['market_type'] = type_key_for_code(normalized)
        item['market_code'] = market_code(normalized)
        item['board_type'] = board_type(normalized)
        data.append(item)
    return ApiResponse(data=data)

def build_probe(db: Session, market_type: str = 'all', limit: int = 500, q: Optional[str] = None, near_only: bool = False) -> dict:
    mt = (market_type or 'all').lower().strip()
    where = [type_sql_where(mt)]
    params = {'limit': limit}
    q_norm = (q or '').strip().lower()
    q_code = normalize_code(q_norm)
    if q_norm:
        where.append(f"({NORMALIZED_CODE_SQL} LIKE :kw_norm OR LOWER(code) LIKE :kw_raw OR name LIKE :kw_raw)")
        params.update({'kw_norm': f'%{q_code or q_norm}%', 'kw_raw': f'%{q_norm}%'})
    stock_sql = f"""
        SELECT code,{NORMALIZED_CODE_SQL} AS normalized_code,name,industry_name,board_name,source
        FROM stock_info
        WHERE {' AND '.join(where)}
        ORDER BY normalized_code
        LIMIT :limit
    """
    stocks = [dict(r) for r in db.execute(text(stock_sql), params).mappings().all()]
    if not stocks:
        return {
            'summary': {
                'total': 0,
                'raw_total': 0,
                'missing_30m': 0,
                'missing_daily': 0,
                'base_ok': 0,
                'near_count': 0,
            },
            'reason_stats': [],
            'items': [],
        }

    codes = [s['code'] for s in stocks]
    clause, in_params = in_clause(codes)

    # technical_indicator 现在存储在 ClickHouse
    ti_sql = f"""
        SELECT ti.* FROM technical_indicator ti
        JOIN (
          SELECT code, period, max(date) AS max_date
          FROM technical_indicator
          WHERE code IN ({','.join(f"'{c}'" for c in codes)}) AND period IN ('30m','daily','5m')
          GROUP BY code, period
        ) x ON ti.code=x.code AND ti.period=x.period AND ti.date=x.max_date
    """
    ti_rows = get_clickhouse().query(ti_sql)
    ti_map = {(r['code'], r['period']): r for r in ti_rows}

    def count_map(sql: str) -> dict:
        return dict(get_clickhouse().query(sql))

    k30 = count_map(f"SELECT code, count() AS cnt FROM minute_kline_period WHERE code IN {clause} AND period='30m' GROUP BY code")
    k5 = count_map(f"SELECT code, count() AS cnt FROM minute_kline_period WHERE code IN {clause} AND period='5m' GROUP BY code")
    kd = count_map(f"SELECT code, count() AS cnt FROM daily_kline WHERE code IN {clause} GROUP BY code")

    kline_sql = f"""
        SELECT code,date,close FROM minute_kline_period WHERE code IN {clause} AND period='30m'
          AND date = (SELECT max(date) FROM minute_kline_period WHERE code = mk.code AND period='30m' AND code IN {clause})
    """
    # Simpler approach: query latest 30m per code
    latest_klines = get_clickhouse().query(
        f"SELECT code,date,close FROM minute_kline_period WHERE code IN {clause} AND period='30m' ORDER BY date DESC LIMIT 1 BY code"
    )
    latest_kline = {r['code']: r for r in latest_klines}

    items = []
    reason_counter = {}
    for s in stocks:
        code = s['code']
        m30 = ti_map.get((code, '30m'))
        daily = ti_map.get((code, 'daily'))
        m5 = ti_map.get((code, '5m'))
        kl = latest_kline.get(code)
        reasons = []
        if not kd.get(code): reasons.append('缺日线')
        if not k30.get(code): reasons.append('缺30m')
        if not k5.get(code): reasons.append('缺5m')
        if not m30: reasons.append('缺30m指标')
        price_near = ma_slope_ok = vol_ok = None
        fail_core = 0
        if m30:
            dev = m30.get('price_ma25_deviation_pct')
            slope = m30.get('ma25_slope_3')
            vr = m30.get('vol_ratio')
            price_near = abs(dev) <= 2.0 if dev is not None else False
            ma_slope_ok = slope >= 0 if slope is not None else False
            vol_ok = vr >= 1.0 if vr is not None else False
            for ok, reason in [(price_near, '价格未贴近MA25'), (ma_slope_ok, 'MA25斜率不足'), (vol_ok, '量能结构不足')]:
                if not ok:
                    fail_core += 1
                    reasons.append(reason)
            if m30.get('is_abnormal_bar') == 1:
                reasons.append('异常K线')
        near_match = bool(m30 and kd.get(code) and k30.get(code) and fail_core <= 1)
        status = '接近满足' if near_match and fail_core == 1 else '基础条件满足' if near_match else '未命中'
        if not reasons:
            reasons = ['基础条件满足']
        for reason in reasons:
            reason_counter[reason] = reason_counter.get(reason, 0) + 1
        item = {
            'code': code, 'name': s.get('name'), 'board_type': board_type(s.get('normalized_code') or code), 'industry_name': s.get('industry_name'),
            'daily_count': int(kd.get(code, 0)), 'k30_count': int(k30.get(code, 0)), 'k5_count': int(k5.get(code, 0)),
            'latest_30m_time': kl.get('date') if kl else (m30.get('date') if m30 else None), 'close_30m': kl.get('close') if kl else None,
            'ma25_30m': m30.get('ma25') if m30 else None, 'ma25_slope_3': m30.get('ma25_slope_3') if m30 else None,
            'price_ma25_deviation_pct': m30.get('price_ma25_deviation_pct') if m30 else None,
            'vol_ma5': m30.get('vol_ma5') if m30 else None, 'vol_ma60': m30.get('vol_ma60') if m30 else None, 'vol_ratio': m30.get('vol_ratio') if m30 else None,
            'price_near_ma25': price_near, 'ma25_slope_ok': ma_slope_ok, 'volume_structure_ok': vol_ok,
            'daily_latest_time': daily.get('date') if daily else None, 'm5_latest_time': m5.get('date') if m5 else None,
            'near_match': near_match, 'core_fail_count': fail_core, 'status': status, 'reasons': '、'.join(reasons)
        }
        if not near_only or item['near_match']:
            items.append(item)

    summary = {
        'total': len(items),
        'raw_total': len(stocks),
        'missing_30m': sum(1 for x in items if x['k30_count'] == 0),
        'missing_daily': sum(1 for x in items if x['daily_count'] == 0),
        'base_ok': sum(1 for x in items if x['status'] == '基础条件满足'),
        'near_count': sum(1 for x in items if x['near_match']),
    }
    reason_stats = [{'reason': k, 'count': v} for k, v in sorted(reason_counter.items(), key=lambda x: x[1], reverse=True)]
    return {'summary': summary, 'reason_stats': reason_stats, 'items': items}

def _compute_funnel(db: Session, market: str) -> dict:
    """Lightweight funnel per market using build_probe logic."""
    probe = build_probe(db, market_type=market, limit=5000, near_only=False)
    s = probe["summary"]
    items = probe.get("items", [])

    total = int(s.get("raw_total") or s.get("total") or 0)

    has_data = [
        i for i in items
        if int(i.get("daily_count") or 0) > 0 and int(i.get("k30_count") or 0) > 0
    ]

    has_ind = [
        i for i in has_data
        if i.get("ma25_30m") is not None
    ]

    price_items = [
        i for i in has_ind
        if bool(i.get("price_near_ma25"))
    ]

    slope_items = [
        i for i in price_items
        if bool(i.get("ma25_slope_ok"))
    ]

    vol_items = [
        i for i in slope_items
        if bool(i.get("volume_structure_ok"))
    ]

    core_items = [
        i for i in vol_items
        if int(i.get("core_fail_count", 999)) == 0
    ]

    near_items = [
        i for i in has_ind
        if bool(i.get("near_match"))
    ]

    base_items = [
        i for i in near_items
        if i.get("status") == "基础条件满足"
    ]

    # A/B/C/D 分层（仅基于 build_probe 可用字段）
    # A: 基础条件满足（核心4全通过），尚不等同于 A 层可执行买点（缺 30m 确认/热点等判断）
    # B: 接近可执行（core_fail_count ≤ 1）但未基础通过
    # C: 有30m指标但未进入接近可执行
    # D: 有数据但无30m指标
    a_items = base_items
    b_items = [
        i for i in near_items
        if i not in a_items
    ]
    c_items = [
        i for i in has_ind
        if i not in near_items
    ]
    d_items = [
        i for i in has_data
        if i not in has_ind
    ]

    # 漏斗阶段（严格递进，数量只会递减）
    stages = [
        {"stage": "总数", "count": total},
        {"stage": "有数据", "count": len(has_data)},
        {"stage": "有30m指标", "count": len(has_ind)},
        {"stage": "价格贴MA25", "count": len(price_items)},
        {"stage": "MA25向上", "count": len(slope_items)},
        {"stage": "量能OK", "count": len(vol_items)},
        {"stage": "核心4通过", "count": len(core_items)},
        {"stage": "基础通过", "count": len(base_items)},
    ]

    # 计算百分比和过率
    for i, st in enumerate(stages):
        st["pct"] = round(st["count"] / total * 100, 1) if total else 0
        if i == 0:
            st["pass_rate"] = 100.0
            st["drop"] = 0
        else:
            prev = stages[i - 1]["count"]
            st["drop"] = max(0, prev - st["count"])
            st["pass_rate"] = round(st["count"] / prev * 100, 1) if prev > 0 else 0

    # 找出最大卡点
    bottleneck = None
    max_drop = 0
    for st in stages[1:]:
        if st["drop"] > max_drop:
            max_drop = st["drop"]
            bottleneck = st["stage"]

    return {
        "market": market,
        "total": total,
        "stages": stages,
        "reason_stats": probe["reason_stats"][:8],
        "bottleneck": bottleneck,
        "bottleneck_drop": max_drop,
        "tiers": {
            "A": {"name": "严格结构", "count": len(a_items), "pct": round(len(a_items) / total * 100, 1) if total else 0},
            "B": {"name": "重点观察", "count": len(b_items), "pct": round(len(b_items) / total * 100, 1) if total else 0},
            "C": {"name": "条件触发", "count": len(c_items), "pct": round(len(c_items) / total * 100, 1) if total else 0},
            "D": {"name": "剔除", "count": len(d_items), "pct": round(len(d_items) / total * 100, 1) if total else 0},
        },
    }


@router.get("/funnel/{market}", response_model=ApiResponse)
def funnel(market: str, db: Session = Depends(get_db)):
    """Per-market funnel diagnostics for 2560."""
    if market not in MARKETS:
        raise HTTPException(status_code=400, detail=f"market must be one of {MARKETS}")
    return ApiResponse(data=_compute_funnel(db, market))


@router.get("/funnel-all", response_model=ApiResponse)
def funnel_all(db: Session = Depends(get_db)):
    """All-market funnel diagnostics."""
    result = {}
    for mkt in MARKETS:
        result[mkt] = _compute_funnel(db, mkt)
    return ApiResponse(data=result)


@router.get('/probe-indicators', response_model=ApiResponse)
def probe_indicators(market_type: str = Query('all'), limit: int = Query(500, ge=1, le=5000), q: Optional[str] = None, near_only: int = Query(0, ge=0, le=1), db: Session = Depends(get_db)):
    return ApiResponse(data=build_probe(db, market_type=market_type, limit=limit, q=q, near_only=bool(near_only)))

@router.get('/probe-reason-stats', response_model=ApiResponse)
def probe_reason_stats(market_type: str = Query('all'), limit: int = Query(1000, ge=1, le=5000), q: Optional[str] = None, near_only: int = Query(0, ge=0, le=1), db: Session = Depends(get_db)):
    data = build_probe(db, market_type=market_type, limit=limit, q=q, near_only=bool(near_only))
    return ApiResponse(data={'summary': data['summary'], 'reason_stats': data['reason_stats']})

@router.post('/run', response_model=ApiResponse)
def run_analysis(payload: RunAnalysisRequest, db: Session = Depends(get_db)):
    mt = (payload.market_type or 'all').lower().strip()
    requested_codes = [c.strip() for c in payload.codes if c and c.strip()]
    accepted_codes, rejected_codes, seen = [], [], set()
    for raw in requested_codes:
        db_code = resolve_db_code(db, raw, mt)
        if db_code and db_code not in seen:
            accepted_codes.append(db_code)
            seen.add(db_code)
        elif not db_code:
            rejected_codes.append(raw)
    if not accepted_codes:
        params = {}
        source_sql = ''
        if payload.source:
            source_sql = ' AND source=:source'
            params['source'] = payload.source
        limit_sql = ''
        if payload.limit:
            limit_sql = ' LIMIT :limit'
            params['limit'] = payload.limit
        sql = f"SELECT code,{NORMALIZED_CODE_SQL} AS normalized_code FROM stock_info WHERE {type_sql_where(mt)}{source_sql} ORDER BY normalized_code{limit_sql}"
        rows = db.execute(text(sql), params).mappings().all()
        accepted_codes = [r['code'] for r in rows if is_supported_code(r['normalized_code'])]
    if not accepted_codes:
        return ApiResponse(data={'processed': 0, 'signals': 0, 'errors': [], 'requested_codes': requested_codes, 'accepted_codes': [], 'rejected_codes': rejected_codes, 'market_type': mt, 'message': '没有可计算股票'})
    result = SignalEngine2560(db).run(codes=accepted_codes, source=payload.source, limit=None)
    result.update({'requested_codes': requested_codes, 'accepted_codes': accepted_codes, 'accepted_market_codes': [market_code(c) for c in accepted_codes], 'rejected_codes': rejected_codes, 'market_type': mt, 'supported_scope': 'sz00/sz30/sh60/sh68; diagnostic indicators available at /probe-indicators'})
    if payload.rebuild_statistics:
        try:
            StatisticsEngine(db).rebuild(result['batch_id'])
        except Exception as exc:
            result['statistics_error'] = str(exc)
    return ApiResponse(data=result)

@router.get('/signals', response_model=ApiResponse)
def signals(code: Optional[str] = None, structure_status: Optional[str] = None, tag: Optional[str] = None, batch_id: Optional[int] = None, selected_signal: Optional[int] = Query(default=None, ge=0, le=1), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    db_code = resolve_db_code(db, code, 'all') if code else None
    code_query = db_code or (normalize_code(code) if code else None)
    return ApiResponse(data=Strategy2560Service(db).list_signals(page=page, page_size=page_size, code=code_query, structure_status=structure_status, tag=tag, batch_id=batch_id, selected_signal=selected_signal))

@router.get('/signals/{signal_id}', response_model=ApiResponse)
def detail(signal_id: int, db: Session = Depends(get_db)):
    data = Strategy2560Service(db).signal_detail(signal_id)
    if not data:
        raise HTTPException(status_code=404, detail='signal not found')
    return ApiResponse(data=data)

@router.get('/complete-cases', response_model=ApiResponse)
def complete(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    return ApiResponse(data=Strategy2560Service(db).complete_cases(limit))

@router.get('/statistics', response_model=ApiResponse)
def stats(stat_type: Optional[str] = None, batch_id: Optional[int] = None, db: Session = Depends(get_db)):
    return ApiResponse(data=Strategy2560Service(db).statistics(stat_type, batch_id))

@router.get('/batches', response_model=ApiResponse)
def batches(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return ApiResponse(data=Strategy2560Service(db).batches(limit))

@router.get('/batches/{batch_id}', response_model=ApiResponse)
def batch(batch_id: int, db: Session = Depends(get_db)):
    data = Strategy2560Service(db).batch_detail(batch_id)
    if not data:
        raise HTTPException(status_code=404, detail='batch not found')
    return ApiResponse(data=data)
