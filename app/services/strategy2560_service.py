from sqlalchemy import text

from app.core.market_scope import SUPPORTED_MARKET_SCOPES, market_sql_where
from app.db.clickhouse import get_clickhouse


NORMALIZED_ANALYSIS_CODE_SQL = (
    "CASE "
    "WHEN LOWER(a.code) LIKE 'sz.%' OR LOWER(a.code) LIKE 'sh.%' THEN SUBSTR(a.code, 4) "
    "WHEN LOWER(a.code) LIKE 'sz%' OR LOWER(a.code) LIKE 'sh%' THEN SUBSTR(a.code, 3) "
    "ELSE a.code END"
)


def normalize_signal_code(raw):
    if raw is None:
        return ""
    s = str(raw).strip().lower().replace("-", "").replace("_", "")
    if s.startswith("sz.") or s.startswith("sh."):
        s = s[3:]
    elif s.startswith("sz") or s.startswith("sh"):
        s = s[2:]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def rows(result):
    return [dict(r._mapping) for r in result]

class Strategy2560Service:
    def __init__(self, db):
        self.db = db
    def overview(self):
        lb = self.db.execute(text("SELECT batch_id,run_time,strategy_code,strategy_version,status FROM analysis_batch WHERE strategy_code='S2560' ORDER BY run_time DESC LIMIT 1")).mappings().first()
        p = {'b': lb['batch_id']} if lb else {}
        wf = 'WHERE batch_id=:b' if lb else ''
        s = self.db.execute(text(f"SELECT COUNT(*) total_signals,SUM(structure_status='结构完整') complete_count,SUM(structure_status='部分满足') partial_count,SUM(structure_status='明显缺失') missing_count,SUM(structure_status='数据不足') data_insufficient_count FROM structure_2560_analysis {wf}"), p).mappings().first()
        t = rows(self.db.execute(text(f"SELECT tag_name,COUNT(*) count FROM structure_2560_tag_detail {wf} GROUP BY tag_name ORDER BY count DESC LIMIT 20"), p))
        return {'latest_batch': dict(lb) if lb else None, 'summary': dict(s) if s else {}, 'tag_distribution': t}
    def list_signals(self, page=1, page_size=50, code=None, structure_status=None, tag=None, batch_id=None, selected_signal=None):
        where=[]; p={'limit': page_size, 'offset': (page-1)*page_size}
        if code:
            normalized_code = normalize_signal_code(code)
            where.append(f"(a.code=:code OR {NORMALIZED_ANALYSIS_CODE_SQL}=:normalized_code)")
            p['code']=code
            p['normalized_code']=normalized_code or code
        if structure_status: where.append('a.structure_status=:st'); p['st']=structure_status
        if batch_id: where.append('a.batch_id=:batch_id'); p['batch_id']=batch_id
        if selected_signal is not None: where.append('a.selected_signal=:selected_signal'); p['selected_signal']=selected_signal
        if tag: where.append('EXISTS (SELECT 1 FROM structure_2560_tag_detail t WHERE t.analysis_id=a.id AND t.tag_name=:tag)'); p['tag']=tag
        ws='WHERE ' + ' AND '.join(where) if where else ''
        total=self.db.execute(text(f'SELECT COUNT(*) FROM structure_2560_analysis a {ws}'), p).scalar_one()
        items=rows(self.db.execute(text(f"SELECT a.id,a.batch_id,a.code,a.name,a.signal_time,a.signal_period,a.price,a.structure_status,a.missing_tags,a.missing_tag_count,a.explain_text,a.data_quality_status,a.selected_signal,s.industry_name,s.board_name FROM structure_2560_analysis a LEFT JOIN stock_info s ON s.code=a.code {ws} ORDER BY a.signal_time DESC,a.id DESC LIMIT :limit OFFSET :offset"), p))
        return {'total': total, 'page': page, 'page_size': page_size, 'items': items}
    def signal_detail(self, signal_id):
        r=self.db.execute(text('SELECT * FROM structure_2560_analysis WHERE id=:id'), {'id': signal_id}).mappings().first()
        if not r: return None
        tags=rows(self.db.execute(text('SELECT tag_code,tag_name,tag_type FROM structure_2560_tag_detail WHERE analysis_id=:id'), {'id': signal_id}))
        return {'base_info': dict(r), 'tags': tags}
    def complete_cases(self, limit=20):
        return rows(self.db.execute(text("SELECT * FROM structure_2560_analysis WHERE structure_status='结构完整' AND selected_signal=1 ORDER BY signal_time DESC LIMIT :l"), {'l': limit}))
    def statistics(self, stat_type=None, batch_id=None):
        where=[]; p={}
        if stat_type: where.append('stat_type=:t'); p['t']=stat_type
        if batch_id: where.append('batch_id=:b'); p['b']=batch_id
        ws='WHERE ' + ' AND '.join(where) if where else ''
        return rows(self.db.execute(text(f'SELECT * FROM structure_2560_statistics {ws} ORDER BY stat_date DESC,id DESC LIMIT 500'), p))
    def batches(self, limit=50):
        return rows(self.db.execute(text('SELECT batch_id,batch_name,run_time,data_source,strategy_code,strategy_version,status,message FROM analysis_batch ORDER BY run_time DESC LIMIT :l'), {'l': limit}))
    def batch_detail(self, batch_id):
        r=self.db.execute(text('SELECT * FROM analysis_batch WHERE batch_id=:b'), {'b': batch_id}).mappings().first()
        return dict(r) if r else None

    def _stock_count(self, market: str) -> int:
        try:
            return int(self.db.execute(text(f"SELECT COUNT(*) FROM stock_info s WHERE {market_sql_where('s.code', market)}")).scalar() or 0)
        except Exception:
            return 0

    @staticmethod
    def _quality_status(missing_symbols: int, duplicate_rows: int, abnormal_bar_count: int, bar_count_bad_symbols: int = 0) -> str:
        if missing_symbols == 0 and duplicate_rows == 0 and abnormal_bar_count == 0 and bar_count_bad_symbols == 0:
            return "ok"
        if duplicate_rows > 0 or abnormal_bar_count > 0 or bar_count_bad_symbols > 0:
            return "warn"
        return "missing"

    def _daily_quality_row(self, market: str, total_symbols: int) -> dict:
        ch = get_clickhouse()
        where = market_sql_where("code", market)
        latest = ch.query_one(f"SELECT max(date) AS latest_day FROM daily_kline WHERE {where}") or {}
        latest_day = latest.get("latest_day")
        if not latest_day:
            return {
                "check_date": None, "data_latest_date": None, "market": market, "period": "daily", "source": "clickhouse",
                "total_symbols": total_symbols, "available_symbols": 0, "missing_symbols": total_symbols,
                "row_count": 0, "expected_rows": total_symbols, "duplicate_keys": 0, "duplicate_rows": 0,
                "abnormal_bar_count": 0, "bar_count_bad_symbols": 0, "status": "missing",
            }
        base = ch.query_one(f"""
            SELECT
                count() AS row_count,
                uniqExact(code) AS available_symbols,
                countIf(open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR high < greatest(open, close) OR low > least(open, close)) AS abnormal_bar_count
            FROM daily_kline
            WHERE {where} AND date = toDate('{latest_day}')
        """) or {}
        dup = ch.query_one(f"""
            SELECT count() AS duplicate_keys, sum(cnt - 1) AS duplicate_rows
            FROM (
                SELECT code, date, count() AS cnt
                FROM daily_kline
                WHERE {where} AND date = toDate('{latest_day}')
                GROUP BY code, date
                HAVING cnt > 1
            )
        """) or {}
        available = int(base.get("available_symbols") or 0)
        duplicate_rows = int(dup.get("duplicate_rows") or 0)
        abnormal = int(base.get("abnormal_bar_count") or 0)
        missing = max(0, total_symbols - available) if total_symbols else 0
        return {
            "check_date": latest_day, "data_latest_date": latest_day, "market": market, "period": "daily", "source": "clickhouse",
            "total_symbols": total_symbols, "available_symbols": available, "missing_symbols": missing,
            "row_count": int(base.get("row_count") or 0), "expected_rows": total_symbols,
            "duplicate_keys": int(dup.get("duplicate_keys") or 0), "duplicate_rows": duplicate_rows,
            "abnormal_bar_count": abnormal, "bar_count_bad_symbols": 0,
            "status": self._quality_status(missing, duplicate_rows, abnormal),
        }

    def _minute_quality_row(self, market: str, period: str, expected_bars: int, total_symbols: int, check_day: str | None) -> dict:
        ch = get_clickhouse()
        where = market_sql_where("code", market)
        latest = ch.query_one(f"""
            SELECT max(toDate(date)) AS latest_day
            FROM minute_kline_period
            WHERE period='{period}' AND {where}
        """) or {}
        latest_day = latest.get("latest_day")
        check_day = check_day or latest_day
        if not check_day:
            return {
                "check_date": None, "data_latest_date": latest_day, "market": market, "period": period, "source": "clickhouse",
                "total_symbols": total_symbols, "available_symbols": 0, "missing_symbols": total_symbols,
                "row_count": 0, "expected_rows": total_symbols * expected_bars,
                "duplicate_keys": 0, "duplicate_rows": 0, "abnormal_bar_count": 0,
                "bar_count_bad_symbols": total_symbols, "status": "missing",
            }
        base = ch.query_one(f"""
            SELECT
                count() AS row_count,
                uniqExact(code) AS available_symbols,
                countIf(open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR high < greatest(open, close) OR low > least(open, close)) AS abnormal_bar_count
            FROM minute_kline_period
            WHERE period='{period}' AND {where} AND toDate(date) = toDate('{check_day}')
        """) or {}
        dup = ch.query_one(f"""
            SELECT count() AS duplicate_keys, sum(cnt - 1) AS duplicate_rows
            FROM (
                SELECT code, date, period, count() AS cnt
                FROM minute_kline_period
                WHERE period='{period}' AND {where} AND toDate(date) = toDate('{check_day}')
                GROUP BY code, date, period
                HAVING cnt > 1
            )
        """) or {}
        counts = ch.query_one(f"""
            SELECT
                countIf(bar_count != {expected_bars}) AS bar_count_bad_symbols,
                countIf(bar_count < {expected_bars}) AS bar_count_under_symbols,
                countIf(bar_count > {expected_bars}) AS bar_count_over_symbols
            FROM (
                SELECT code, count() AS bar_count
                FROM minute_kline_period
                WHERE period='{period}' AND {where} AND toDate(date) = toDate('{check_day}')
                GROUP BY code
            )
        """) or {}
        available = int(base.get("available_symbols") or 0)
        duplicate_rows = int(dup.get("duplicate_rows") or 0)
        abnormal = int(base.get("abnormal_bar_count") or 0)
        bad_symbols = int(counts.get("bar_count_bad_symbols") or 0)
        missing = max(0, total_symbols - available) if total_symbols else 0
        return {
            "check_date": check_day, "data_latest_date": latest_day, "market": market, "period": period, "source": "clickhouse",
            "total_symbols": total_symbols, "available_symbols": available, "missing_symbols": missing,
            "row_count": int(base.get("row_count") or 0), "expected_rows": total_symbols * expected_bars,
            "duplicate_keys": int(dup.get("duplicate_keys") or 0), "duplicate_rows": duplicate_rows,
            "abnormal_bar_count": abnormal, "bar_count_bad_symbols": bad_symbols,
            "bar_count_under_symbols": int(counts.get("bar_count_under_symbols") or 0),
            "bar_count_over_symbols": int(counts.get("bar_count_over_symbols") or 0),
            "expected_bars_per_symbol": expected_bars,
            "status": self._quality_status(missing, duplicate_rows, abnormal, bad_symbols),
        }

    def data_quality_summary(self):
        result = []
        for market in SUPPORTED_MARKET_SCOPES:
            total_symbols = self._stock_count(market)
            daily_row = self._daily_quality_row(market, total_symbols)
            target_day = daily_row.get("check_date")
            result.append(daily_row)
            result.append(self._minute_quality_row(market, "5m", 48, total_symbols, target_day))
            result.append(self._minute_quality_row(market, "30m", 8, total_symbols, target_day))
        return result
