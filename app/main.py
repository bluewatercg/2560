from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.api.strategy2560 import router as strategy_router
from app.api.strategy2568 import router as strategy2568_router
from app.api.strategy2568_report import router as strategy2568_report_router
from app.api.data_quality import router as quality_router
from app.api.latest import router as latest_router
from app.api.jobs import router as jobs_router
from app.api.import_data import router as import_router
from app.db.session import ping_database
from app.db.clickhouse import get_clickhouse

app = FastAPI(title='2560结构分析系统', description='结构化行情分析与历史复盘，不提供买卖决策。', version='3.0.0')
app.include_router(strategy_router)
app.include_router(strategy2568_router)
app.include_router(strategy2568_report_router)
app.include_router(quality_router)
app.include_router(latest_router)
app.include_router(jobs_router)
app.include_router(import_router)
app.mount('/static', StaticFiles(directory='app/static'), name='static')

@app.get('/health')
def health():
    db_ok = False
    ch_ok = False
    try:
        db_ok = ping_database()
    except Exception:
        pass
    try:
        ch_ok = get_clickhouse().ping()
    except Exception:
        pass
    return {
        'status': 'ok' if db_ok and ch_ok else ('partial' if ch_ok else 'degraded'),
        'database': db_ok,
        'clickhouse': ch_ok,
    }

@app.get('/', response_class=HTMLResponse)
def index():
    with open('app/static/index.html', 'r', encoding='utf-8') as f:
        return f.read()
