from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.api.strategy2560 import router as strategy_router
from app.api.data_quality import router as quality_router
from app.db.session import ping_database

app = FastAPI(title='2560结构分析系统', description='结构化行情分析与历史复盘，不提供买卖决策。', version='3.0.0')
app.include_router(strategy_router)
app.include_router(quality_router)
app.mount('/static', StaticFiles(directory='app/static'), name='static')

@app.get('/health')
def health():
    try:
        return {'status': 'ok', 'database': ping_database()}
    except Exception as exc:
        return {'status': 'warning', 'database': False, 'message': str(exc)}

@app.get('/', response_class=HTMLResponse)
def index():
    with open('app/static/index.html', 'r', encoding='utf-8') as f:
        return f.read()
