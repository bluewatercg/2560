from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import ApiResponse
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
    if type_key in SUPPORTED_TYPES:
        return f"{n} LIKE '{SUPPORTED_TYPES[type_key][1]}%'"
    if type_key == 'sz':
        return f"({n} LIKE '00%' OR {n} LIKE '30%')"
    if type_key == 'sh':
        return f"({n} LIKE '60%' OR {n} LIKE '68%')"
    return supported_sql_where()

def market_type_matches(code: str, market_type: str) -> bool:
    t = type_key_for_code(code)
    mt = (market_type or 'all').lower()
    return mt in ('', 'all') or mt == t or (mt == 'sz' and t in ('sz00', 'sz30')) or (mt == 'sh' and t in ('sh60', 'sh68'))

def resolve_db_code(db: Session, raw_code: str, market_type: str = 'all') -> str | None:
    raw = (raw_code or '').strip()
    norm = normalize_code(raw)
    if not norm or not is_supported_code(norm) or not market_type_matches(norm, market_type):
        return None
    candidates = [raw, norm, 'sz' + norm, 'sh' + norm, 'sz.' + norm, 'sh.' + norm]
    sql = (
        f"SELECT code FROM stock_info WHERE ({NORMALIZED_CODE_SQL}=:norm OR code IN :candidates) "
        f"AND {type_sql_where((market_type or 'all').lower())} ORDER BY code LIMIT 1"
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

@router.get('/overview', response_model=ApiResponse)
def overview(db: Session = Depends(get_db)):
    return ApiResponse(data=Strategy2560Service(db).overview())

@router.get('/stocks', response_model=ApiResponse)
def stocks(q: Optional[str] = None, market_type: Optional[str] = Query(default='all'), limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    mt = (market_type or 'all').lower()
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
    mt = (market_type or 'all').lower()
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
        return {'summary': {'total': 0, 'missing_30m': 0, 'missing_daily': 0, 'base_ok': 0, 'near_count': 0}, 'reason_stats': [], 'items': []}

    codes = [s['code'] for s in stocks]
    clause, in_params = in_clause(codes)

    ti_sql = f"""
        SELECT ti.* FROM technical_indicator ti
        JOIN (
          SELECT code, period, MAX(date) AS max_date
          FROM technical_indicator
          WHERE code IN {clause} AND period IN ('30m','daily','5m')
          GROUP BY code, period
        ) x ON ti.code=x.code AND ti.period=x.period AND ti.date=x.max_date
    """
    ti_rows = [dict(r) for r in db.execute(text(ti_sql), in_params).mappings().all()]
    ti_map = {(r['code'], r['period']): r for r in ti_rows}

    def count_map(sql: str) -> dict:
        return dict(db.execute(text(sql), in_params).fetchall())

    k30 = count_map(f"SELECT code, COUNT(*) cnt FROM minute_kline_period WHERE code IN {clause} AND period='30m' GROUP BY code")
    k5 = count_map(f"SELECT code, COUNT(*) cnt FROM minute_kline_period WHERE code IN {clause} AND period='5m' GROUP BY code")
    kd = count_map(f"SELECT code, COUNT(*) cnt FROM daily_kline WHERE code IN {clause} GROUP BY code")

    kline_sql = f"""
        SELECT mk.code,mk.date,mk.close FROM minute_kline_period mk
        JOIN (
          SELECT code, MAX(date) AS max_date
          FROM minute_kline_period
          WHERE code IN {clause} AND period='30m'
          GROUP BY code
        ) x ON mk.code=x.code AND mk.date=x.max_date
        WHERE mk.period='30m'
    """
    latest_kline = {r['code']: dict(r) for r in db.execute(text(kline_sql), in_params).mappings().all()}

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

@router.get('/probe-indicators', response_model=ApiResponse)
def probe_indicators(market_type: str = Query('all'), limit: int = Query(500, ge=1, le=5000), q: Optional[str] = None, near_only: int = Query(0, ge=0, le=1), db: Session = Depends(get_db)):
    return ApiResponse(data=build_probe(db, market_type=market_type, limit=limit, q=q, near_only=bool(near_only)))

@router.get('/probe-reason-stats', response_model=ApiResponse)
def probe_reason_stats(market_type: str = Query('all'), limit: int = Query(1000, ge=1, le=5000), q: Optional[str] = None, near_only: int = Query(0, ge=0, le=1), db: Session = Depends(get_db)):
    data = build_probe(db, market_type=market_type, limit=limit, q=q, near_only=bool(near_only))
    return ApiResponse(data={'summary': data['summary'], 'reason_stats': data['reason_stats']})

@router.post('/run', response_model=ApiResponse)
def run_analysis(payload: RunAnalysisRequest, db: Session = Depends(get_db)):
    mt = (payload.market_type or 'all').lower()
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
