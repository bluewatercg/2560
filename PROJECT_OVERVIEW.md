# PROJECT_OVERVIEW — 2560结构分析系统

> 结构化行情分析与历史复盘系统 | v3.0.0

---

## 目录 (TOC)

- [1. 项目总览](#1-项目总览)
- [2. 目录结构](#2-目录结构)
- [3. 架构说明](#3-架构说明)
- [4. 数据库 Schema](#4-数据库-schema)
- [5. 后端 — 核心模块](#5-后端--核心模块)
  - [5.1 应用入口](#51-应用入口-appmainpy)
  - [5.2 配置层](#52-配置层)
  - [5.3 数据库层](#53-数据库层)
  - [5.4 API 层](#54-api-层)
  - [5.5 服务层](#55-服务层)
  - [5.6 数据模型](#56-数据模型)
- [6. 前端 — WebUI](#6-前端--webui)
- [7. 运维脚本](#7-运维脚本)
- [8. 依赖与环境](#8-依赖与环境)
- [9. 日常运维指南](#9-日常运维指南)

---

## 1. 项目总览

**项目名称**: 2560结构分析系统 (strategy2560)

**定位**: A股全市场结构化行情分析工具。通过 30 分钟 K 线识别"2560 结构"（MA25 回踩 + 量能确认 + 日线趋势过滤 + 5 分钟确认），生成信号标签和可解释文本，供复盘参考。

**核心设计理念**: CLI 负责"算"，WebUI 负责"看"。数据处理/指标计算/信号扫描走命令行脚本，结果展示/交互看板走 FastAPI + 单页前端。

**技术栈**:
- **后端**: FastAPI 0.111 + SQLAlchemy 2.0 + PyMySQL
- **数据库**: MySQL 8.x (utf8mb4)
- **计算**: pandas 2.2 + numpy 1.26
- **前端**: 原生 HTML/CSS/JS 单页应用
- **数据源**: pytdx (通达信 vipdoc 本地数据 + 实时行情)

---

## 2. 目录结构

```
strategy2560_project_v2_engine/
├── .env                              # 环境变量 (DB 密码等)
├── .env.example                      # 环境变量模板
├── .gitignore                        # Git 忽略规则
├── BUILD_REPORT.json                 # 构建报告 (元数据)
├── PATCH_REPORT.json                 # 补丁报告 (元数据)
├── README.md                         # 项目主 README
├── README_2560_DAILY_OPS.md          # 每日运维指南
├── README_PATCH.md                   # WebUI 补丁说明
├── requirements.txt                  # Python 依赖 (主)
├── requirements.backend.txt          # Python 依赖 (后端)
│
├── app/                              # FastAPI 应用
│   ├── __init__.py
│   ├── main.py                       # 应用入口
│   ├── api/                          # 路由层
│   │   ├── __init__.py
│   │   ├── strategy2560.py           # 2560 策略 API
│   │   └── data_quality.py           # 数据质量 API
│   ├── core/                         # 核心配置
│   │   ├── __init__.py
│   │   └── config.py                 # Settings (pydantic-settings)
│   ├── db/                           # 数据库层
│   │   ├── __init__.py
│   │   ├── session.py                # Engine + Session
│   │   └── repository.py             # 数据访问层 (KlineRepository)
│   ├── schemas/                      # Pydantic 模型
│   │   ├── __init__.py
│   │   └── common.py                 # ApiResponse
│   ├── services/                     # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── config_service.py         # 策略参数管理
│   │   ├── future_return_engine.py   # 未来收益计算 (占位)
│   │   ├── indicator_engine.py       # 技术指标计算
│   │   ├── signal_engine_2560.py     # 2560 核心信号引擎
│   │   ├── statistics_engine.py      # 统计聚合引擎
│   │   ├── strategy2560_service.py   # 查询服务
│   │   └── tag_service.py            # 标签体系
│   └── static/                       # WebUI 前端
│       ├── index.html                # 主页面
│       ├── app.js                    # 前端逻辑
│       ├── styles.css                # 主样式
│       ├── diagnostic_append.js      # 诊断面板 (增量)
│       ├── diagnostic_menu_append.js # 诊断菜单 (增量)
│       ├── styles.diagnostic.css     # 诊断样式
│       ├── styles.diagnostic-menu.css
│       ├── styles.market-filter.css
│       └── styles.market-probe.css
│
├── docs/
│   └── README_V2.4.md                # V2.4 需求说明
│
├── scripts/                          # 运维脚本
│   ├── apply_schema.py               # 建表脚本
│   ├── backfill_future_returns.py    # 回补未来收益
│   ├── build_30m_from_5m.py          # 5m → 30m 聚合
│   ├── daily_update_2560.sh          # 每日全量更新
│   ├── daily_update_incremental.sh   # 每日增量更新
│   ├── fill_recent_with_pytdx_hq.py  # pytdx 实时补数据
│   ├── import_vipdoc_with_pytdx.py   # 导入通达信本地数据
│   ├── rebuild_statistics.py         # 重建统计
│   ├── rebuild_technical_indicator.py# 重算技术指标
│   ├── run_2560_analysis.py          # 运行 2560 分析
│   ├── run_with_path.sh              # 带 PATH 启动脚本
│   └── start_webui.sh                # 启动 WebUI
│
└── sql/
    └── 2560_schema_v2.4.sql          # 数据库建表 DDL
```

---

## 3. 架构说明

```
┌─────────────────────────────────────────────────────────┐
│                      WebUI (浏览器)                      │
│  总览 | 入库计算 | 摸底指标 | 信号列表 | 完整结构 | ...    │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP REST
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  FastAPI (app/main.py)                   │
│                                                         │
│  /api/strategy/2560/*   →  strategy2560.py 路由          │
│  /api/data-quality/*    →  data_quality.py 路由          │
│  /static/*              →  静态文件                       │
└────────────────────────┬────────────────────────────────┘
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
┌───────────────────────┐  ┌──────────────────────────┐
│   Strategy2560Service │  │   SignalEngine2560       │
│   (查询/展示)          │  │   (信号扫描/入库)         │
│                       │  │                          │
│   - overview()        │  │   - run()                │
│   - list_signals()    │  │   - scan()               │
│   - signal_detail()   │  │   - confirm5()           │
│   - batches()         │  │                          │
│   - statistics()      │  │   ┌──────────────────┐   │
│   - data_quality()    │  │   │ TagService       │   │
│                       │  │   │ - build_tags()   │   │
│   ┌─────────────────┐ │  │   │ - structure_status│  │
│   │ KlineRepository │ │  │   │ - explain_text() │   │
│   │ - read_daily()  │ │  │   └──────────────────┘   │
│   │ - read_minute() │ │  │   ┌──────────────────┐   │
│   │ - upsert_*()    │ │  │   │ IndicatorEngine │    │
│   └─────────────────┘ │  │   │ - enrich_*()    │    │
└───────────┬───────────┘  │   └──────────────────┘   │
            │              └──────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────────┐
│                   MySQL 数据库                           │
│  stock_info | daily_kline | minute_kline_period          │
│  technical_indicator | structure_2560_analysis            │
│  structure_2560_tag_detail | analysis_batch               │
│  structure_2560_statistics | data_quality_check           │
│  strategy_config                                          │
└─────────────────────────────────────────────────────────┘
```

### 数据流

1. **数据采集** → `import_vipdoc_with_pytdx.py` 读取通达信 vipdoc → 写入 `daily_kline` + `minute_kline_period`
2. **K 线聚合** → `build_30m_from_5m.py` 从 5m 聚合为 30m
3. **指标计算** → `rebuild_technical_indicator.py` 计算 MA/ATR/VOL 等 → 写入 `technical_indicator`
4. **信号扫描** → `run_2560_analysis.py` (CLI) 或 `POST /api/strategy/2560/run` (Web) → 写入 `structure_2560_analysis` + `structure_2560_tag_detail`
5. **统计聚合** → `StatisticsEngine.rebuild()` → 写入 `structure_2560_statistics`
6. **Web 展示** → 前端通过 REST API 读取结果

---

## 4. 数据库 Schema

DDL 文件: `sql/2560_schema_v2.4.sql`

### 表清单

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `strategy_config` | 策略参数配置表 | strategy_code, config_key, config_value |
| `analysis_batch` | 分析批次记录 | batch_id, run_time, status |
| `minute_kline_period` | 分钟级 K 线 (5m/30m) | code, period, date |
| `technical_indicator` | 技术指标 (MA/ATR/VOL) | code, period, date, ma25, atr14... |
| `structure_2560_analysis` | 2560 结构分析结果 | signal_uid, code, structure_status, explain_text |
| `structure_2560_tag_detail` | 信号标签明细 | analysis_id, tag_code, tag_type |
| `structure_2560_statistics` | 聚合统计 | batch_id, stat_type, sample_count |
| `data_quality_check` | 数据质量检查 | check_date, period, status |

### 标签体系 (12 种)

| tag_code | tag_name | tag_type | 触发条件 |
|----------|----------|----------|----------|
| `LACK_VOLUME` | #缺量 | negative | volume_ok 或 volume_structure_ok 为 false |
| `HIGH_POSITION` | #高位 | negative | near_resistance 为 true |
| `SIDEWAYS` | #震荡 | negative | volatility_ok 为 false |
| `NO_BREAKOUT` | #未突破 | negative | breakout_ok 为 false |
| `AGAINST_TREND` | #逆势 | negative | trend_price_ok 为 false |
| `WEAK_TREND` | #趋势走弱 | negative | trend_slope_ok 为 false |
| `NO_CONFIRM` | #未确认 | negative | pullback_ok 或 bullish_confirm 为 false |
| `PRICE_AWAY_MA25` | #偏离MA25 | negative | price_near_ma25 为 false |
| `MA25_WEAK` | #MA25走弱 | negative | ma25_slope_ok 为 false |
| `DATA_INSUFFICIENT` | #数据不足 | negative | data_quality_status != 'normal' |
| `COMPLETE_STRUCTURE` | #结构完整 | positive | 无任何 negative 标签 |

### 结构状态 (structure_status)

- **结构完整**: 无任何 negative 标签
- **部分满足**: 1-2 个 negative 标签
- **明显缺失**: 3+ 个 negative 标签
- **数据不足**: 包含 `DATA_INSUFFICIENT` 标签

---

## 5. 后端 — 核心模块

### 5.1 应用入口 — `app/main.py`

FastAPI 应用工厂。注册两个路由 (`strategy2560`, `data_quality`)，挂载静态文件，提供 `/health` 健康检查和根路径返回 HTML。

版本: `3.0.0`

```python
# app/main.py
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
```

### 5.2 配置层

#### `app/core/config.py` — 环境变量管理

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_HOST: str = '192.168.1.254'
    DB_PORT: int = 3306
    DB_USER: str = 'watchlist_decision_support'
    DB_PASSWORD: str = ''
    DB_NAME: str = 'watchlist_decision_support'
    DB_POOL_SIZE: int = 20
    APP_HOST: str = '0.0.0.0'
    APP_PORT: int = 8000
    APP_ENV: str = 'local'
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    @property
    def sqlalchemy_url(self) -> str:
        return f'mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4'

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

#### `app/services/config_service.py` — 策略参数服务

```python
from __future__ import annotations
from typing import Any, Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_CONFIG: dict[str, Any] = {
    'ma_price_period': 25,
    'vol_short_period': 5,
    'vol_long_period': 60,
    'pullback_threshold_pct': 2.0,
    'min_volume_ratio': 1.0,
    'resistance_threshold': 0.95,
    'breakout_threshold': 1.0,
    'atr_period': 14,
    'atr_compare_period': 20,
    'atr_weak_ratio': 0.85,
    'breakout_period': 20,
    'signal_cooldown_days': 3,
    'ma_slope_medium_threshold': 0.0,
}

def _cast(value: str, value_type: str):
    if value_type == 'int':
        return int(float(value))
    if value_type == 'double':
        return float(value)
    if value_type == 'bool':
        return str(value).lower() in {'1','true','yes','y'}
    return value

class ConfigService:
    def __init__(self, db: Session):
        self.db = db

    def load_strategy_config(self, strategy_code: str = 'S2560') -> dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        try:
            rows = self.db.execute(text('SELECT config_key,config_value,value_type FROM strategy_config WHERE strategy_code=:s AND enabled=1'), {'s': strategy_code}).mappings().all()
            for r in rows:
                cfg[r['config_key']] = _cast(r['config_value'], r['value_type'])
        except Exception:
            pass
        return cfg
```

### 5.3 数据库层

#### `app/db/session.py` — 数据库连接

```python
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()
engine = create_engine(
    settings.sqlalchemy_url,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=max(settings.DB_POOL_SIZE, 10),
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ping_database() -> bool:
    with engine.connect() as conn:
        return conn.execute(text('SELECT 1')).scalar_one() == 1
```

#### `app/db/repository.py` — 数据访问层

```python
from __future__ import annotations
from typing import Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

class KlineRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_codes(self, source: Optional[str] = None, limit: Optional[int] = None) -> list[str]:
        sql = 'SELECT code FROM stock_info'
        params = {}
        if source:
            sql += ' WHERE source=:source'
            params['source'] = source
        sql += ' ORDER BY code'
        if limit:
            sql += ' LIMIT :limit'
            params['limit'] = limit
        return [r[0] for r in self.db.execute(text(sql), params).all()]

    def get_stock_info(self, code: str) -> dict:
        row = self.db.execute(text('SELECT * FROM stock_info WHERE code=:code'), {'code': code}).mappings().first()
        return dict(row) if row else {'code': code, 'name': None}

    def read_daily(self, code: str, source: Optional[str] = None, lookback: Optional[int] = None) -> pd.DataFrame:
        sql = 'SELECT code,date,open,high,low,close,volume,amount,source FROM daily_kline WHERE code=:code'
        params = {'code': code}
        if source:
            sql += ' AND source=:source'
            params['source'] = source
        sql += ' ORDER BY date'
        df = pd.read_sql(text(sql), self.db.bind, params=params)
        return df.tail(lookback).reset_index(drop=True) if lookback else df.reset_index(drop=True)

    def read_minute(self, code: str, period: str, source: Optional[str] = None, lookback: Optional[int] = None) -> pd.DataFrame:
        params = {'code': code, 'period': period}
        sf = ''
        if source:
            params['source'] = source
            sf = ' AND source=:source'
        try:
            df = pd.read_sql(text(f"""
                SELECT code,date,period,open,high,low,close,volume,amount,source
                FROM minute_kline_period
                WHERE code=:code AND period=:period {sf}
                ORDER BY date
            """), self.db.bind, params=params)
        except Exception:
            df = pd.DataFrame()
        if df.empty and period == '5m':
            params = {'code': code}
            sf = ''
            if source:
                params['source'] = source
                sf = ' AND source=:source'
            df = pd.read_sql(text(f"""
                SELECT code,date,'5m' AS period,open,high,low,close,volume,amount,source
                FROM minute_kline
                WHERE code=:code {sf}
                ORDER BY date
            """), self.db.bind, params=params)
        return df.tail(lookback).reset_index(drop=True) if lookback and not df.empty else df.reset_index(drop=True)

    def upsert_indicators(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.db.execute(text("""
            INSERT INTO technical_indicator
            (code,period,date,source,stock_status,is_st,ma25,ma60,ma200,ma25_slope_3,ma60_slope_3,atr14,atr20_avg,vol_ma5,vol_ma60,vol_ratio,vol_ma5_cross_vol_ma60,price_ma25_deviation_pct,high_20,low_20,low_30,resistance_level,is_abnormal_bar,data_quality_status)
            VALUES
            (:code,:period,:date,:source,:stock_status,:is_st,:ma25,:ma60,:ma200,:ma25_slope_3,:ma60_slope_3,:atr14,:atr20_avg,:vol_ma5,:vol_ma60,:vol_ratio,:vol_ma5_cross_vol_ma60,:price_ma25_deviation_pct,:high_20,:low_20,:low_30,:resistance_level,:is_abnormal_bar,:data_quality_status)
            ON DUPLICATE KEY UPDATE
            ma25=VALUES(ma25),ma60=VALUES(ma60),ma200=VALUES(ma200),ma25_slope_3=VALUES(ma25_slope_3),ma60_slope_3=VALUES(ma60_slope_3),atr14=VALUES(atr14),atr20_avg=VALUES(atr20_avg),vol_ma5=VALUES(vol_ma5),vol_ma60=VALUES(vol_ma60),vol_ratio=VALUES(vol_ratio),vol_ma5_cross_vol_ma60=VALUES(vol_ma5_cross_vol_ma60),price_ma25_deviation_pct=VALUES(price_ma25_deviation_pct),high_20=VALUES(high_20),low_20=VALUES(low_20),low_30=VALUES(low_30),resistance_level=VALUES(resistance_level),is_abnormal_bar=VALUES(is_abnormal_bar),data_quality_status=VALUES(data_quality_status),updated_at=CURRENT_TIMESTAMP
        """), rows)

    def insert_batch(self, batch: dict) -> None:
        self.db.execute(text("""
            INSERT INTO analysis_batch (batch_id,batch_name,run_time,data_source,strategy_code,strategy_version,param_snapshot,status,message)
            VALUES (:batch_id,:batch_name,:run_time,:data_source,:strategy_code,:strategy_version,:param_snapshot,:status,:message)
            ON DUPLICATE KEY UPDATE status=VALUES(status), message=VALUES(message), updated_at=CURRENT_TIMESTAMP
        """), batch)

    def update_batch_status(self, batch_id: int, status: str, message: str = '') -> None:
        self.db.execute(text('UPDATE analysis_batch SET status=:status,message=:message WHERE batch_id=:batch_id'), {'batch_id': batch_id, 'status': status, 'message': message})

    def upsert_analysis(self, row: dict) -> int:
        self.db.execute(text("""
            INSERT INTO structure_2560_analysis
            (signal_uid,batch_id,strategy_code,strategy_version,code,name,signal_time,signal_period,price,source,stock_status,has_2560_signal,price_near_ma25,ma25_slope_ok,volume_structure_ok,abnormal_filter_ok,trend_price_ok,trend_slope_ok,volatility_ok,breakout_ok,volume_ok,near_resistance,pullback_ok,bullish_confirm,structure_status,strength_score_raw,missing_tags,missing_tag_count,explain_text,data_quality_status,is_duplicate_signal,selected_signal)
            VALUES
            (:signal_uid,:batch_id,:strategy_code,:strategy_version,:code,:name,:signal_time,:signal_period,:price,:source,:stock_status,:has_2560_signal,:price_near_ma25,:ma25_slope_ok,:volume_structure_ok,:abnormal_filter_ok,:trend_price_ok,:trend_slope_ok,:volatility_ok,:breakout_ok,:volume_ok,:near_resistance,:pullback_ok,:bullish_confirm,:structure_status,:strength_score_raw,:missing_tags,:missing_tag_count,:explain_text,:data_quality_status,:is_duplicate_signal,:selected_signal)
            ON DUPLICATE KEY UPDATE
            batch_id=VALUES(batch_id),name=VALUES(name),price=VALUES(price),structure_status=VALUES(structure_status),strength_score_raw=VALUES(strength_score_raw),missing_tags=VALUES(missing_tags),missing_tag_count=VALUES(missing_tag_count),explain_text=VALUES(explain_text),data_quality_status=VALUES(data_quality_status),updated_at=CURRENT_TIMESTAMP
        """), row)
        return int(self.db.execute(text('SELECT id FROM structure_2560_analysis WHERE signal_uid=:uid'), {'uid': row['signal_uid']}).scalar_one())

    def replace_tags(self, analysis_id: int, batch_id: int, code: str, signal_time: int, tags: list[dict]) -> None:
        self.db.execute(text('DELETE FROM structure_2560_tag_detail WHERE analysis_id=:id'), {'id': analysis_id})
        if not tags:
            return
        rows = [{'analysis_id': analysis_id, 'batch_id': batch_id, 'code': code, 'signal_time': signal_time, **t} for t in tags]
        self.db.execute(text("""
            INSERT INTO structure_2560_tag_detail (analysis_id,batch_id,code,signal_time,tag_code,tag_name,tag_type)
            VALUES (:analysis_id,:batch_id,:code,:signal_time,:tag_code,:tag_name,:tag_type)
        """), rows)
```

### 5.4 API 层

#### `app/api/strategy2560.py` — 2560 策略路由

前缀: `/api/strategy/2560`

| Method | Path | 功能 |
|--------|------|------|
| GET | `/overview` | 总览 (信号数、完整率、标签分布) |
| GET | `/stocks` | 股票列表 (搜索/筛选) |
| POST | `/run` | 执行 2560 分析 (Web 入库计算) |
| GET | `/signals` | 信号列表 (分页/筛选) |
| GET | `/signals/{id}` | 信号详情 |
| GET | `/probe-indicators` | 摸底指标 (诊断) |
| GET | `/probe-reason-stats` | 摸底原因统计 |
| GET | `/complete-cases` | 完整结构案例 |
| GET | `/statistics` | 结构统计 |
| GET | `/batches` | 批次列表 |

```python
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
```

#### `app/api/data_quality.py` — 数据质量路由

前缀: `/api/data-quality`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.services.strategy2560_service import Strategy2560Service

router = APIRouter(prefix='/api/data-quality', tags=['data-quality'])

@router.get('/summary', response_model=ApiResponse)
def summary(db: Session = Depends(get_db)):
    return ApiResponse(data=Strategy2560Service(db).data_quality_summary())
```

### 5.5 服务层

#### `app/services/indicator_engine.py` — 技术指标计算

```python
import numpy as np
import pandas as pd

def slope_pct(series: pd.Series, periods: int = 3) -> pd.Series:
    prev = series.shift(periods)
    return (series - prev) / prev.replace(0, np.nan) * 100.0

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df['close'].shift(1)
    tr = pd.concat([(df['high']-df['low']), (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def enrich_indicators(df: pd.DataFrame, period: str, source: str | None, cfg: dict, stock_status: str = 'NORMAL', is_st: int = 0) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy().sort_values('date').reset_index(drop=True)
    out['period'] = period
    if 'source' not in out.columns:
        out['source'] = source or 'default'
    for col in ['open','high','low','close','volume','amount']:
        out[col] = pd.to_numeric(out[col], errors='coerce')
    ma_period = int(cfg.get('ma_price_period', 25))
    vol_short = int(cfg.get('vol_short_period', 5))
    vol_long = int(cfg.get('vol_long_period', 60))
    atr_period = int(cfg.get('atr_period', 14))
    atr_compare = int(cfg.get('atr_compare_period', 20))
    breakout_period = int(cfg.get('breakout_period', 20))
    out['ma25'] = out['close'].rolling(ma_period, min_periods=ma_period).mean()
    out['ma60'] = out['close'].rolling(60, min_periods=60).mean()
    out['ma200'] = out['close'].rolling(200, min_periods=200).mean()
    out['ma25_slope_3'] = slope_pct(out['ma25'])
    out['ma60_slope_3'] = slope_pct(out['ma60'])
    out['atr14'] = atr(out, atr_period)
    out['atr20_avg'] = out['atr14'].rolling(atr_compare, min_periods=atr_compare).mean()
    out['vol_ma5'] = out['volume'].rolling(vol_short, min_periods=vol_short).mean()
    out['vol_ma60'] = out['volume'].rolling(vol_long, min_periods=vol_long).mean()
    out['vol_ratio'] = out['vol_ma5'] / out['vol_ma60'].replace(0, np.nan)
    out['vol_ma5_cross_vol_ma60'] = ((out['vol_ratio'].shift(1) <= 1.0) & (out['vol_ratio'] > 1.0)).astype('Int64')
    out['price_ma25_deviation_pct'] = (out['close'] - out['ma25']) / out['ma25'].replace(0, np.nan) * 100.0
    out['high_20'] = out['high'].shift(1).rolling(breakout_period, min_periods=breakout_period).max()
    out['low_20'] = out['low'].shift(1).rolling(20, min_periods=20).min()
    out['low_30'] = out['low'].shift(1).rolling(30, min_periods=30).min()
    out['resistance_level'] = out['high_20']
    out['is_abnormal_bar'] = (out[['open','high','low','close','volume']].isna().any(axis=1) | ((out['open']==out['high']) & (out['high']==out['low']) & (out['low']==out['close'])) | (out['volume'].fillna(0)<=0)).astype(int)
    out['data_quality_status'] = np.where(out['is_abnormal_bar'] == 1, 'abnormal', 'normal')
    out['stock_status'] = stock_status
    out['is_st'] = is_st
    return out

def to_indicator_rows(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    cols = ['code','period','date','source','stock_status','is_st','ma25','ma60','ma200','ma25_slope_3','ma60_slope_3','atr14','atr20_avg','vol_ma5','vol_ma60','vol_ratio','vol_ma5_cross_vol_ma60','price_ma25_deviation_pct','high_20','low_20','low_30','resistance_level','is_abnormal_bar','data_quality_status']
    return df[cols].replace({np.nan: None}).to_dict('records')
```

#### `app/services/tag_service.py` — 标签体系

```python
TAG = {
    'LACK_VOLUME': '#缺量',
    'HIGH_POSITION': '#高位',
    'SIDEWAYS': '#震荡',
    'NO_BREAKOUT': '#未突破',
    'AGAINST_TREND': '#逆势',
    'WEAK_TREND': '#趋势走弱',
    'NO_CONFIRM': '#未确认',
    'PRICE_AWAY_MA25': '#偏离MA25',
    'MA25_WEAK': '#MA25走弱',
    'DATA_INSUFFICIENT': '#数据不足',
    'COMPLETE_STRUCTURE': '#结构完整',
}

def build_tags(row: dict) -> list[dict]:
    tags = []
    def add(code, tag_type='negative'):
        tags.append({'tag_code': code, 'tag_name': TAG[code], 'tag_type': tag_type})
    if not row.get('volume_ok') or not row.get('volume_structure_ok'):
        add('LACK_VOLUME')
    if row.get('near_resistance'):
        add('HIGH_POSITION')
    if not row.get('volatility_ok'):
        add('SIDEWAYS')
    if not row.get('breakout_ok'):
        add('NO_BREAKOUT')
    if not row.get('trend_price_ok'):
        add('AGAINST_TREND')
    if not row.get('trend_slope_ok'):
        add('WEAK_TREND')
    if not row.get('pullback_ok') or not row.get('bullish_confirm'):
        add('NO_CONFIRM')
    if not row.get('price_near_ma25'):
        add('PRICE_AWAY_MA25')
    if not row.get('ma25_slope_ok'):
        add('MA25_WEAK')
    if row.get('data_quality_status') != 'normal':
        add('DATA_INSUFFICIENT')
    if not tags:
        add('COMPLETE_STRUCTURE', 'positive')
    return tags

def structure_status(tags: list[dict]) -> str:
    neg = len([t for t in tags if t.get('tag_type') == 'negative'])
    if any(t['tag_code'] == 'DATA_INSUFFICIENT' for t in tags):
        return '数据不足'
    if neg == 0:
        return '结构完整'
    if neg <= 2:
        return '部分满足'
    return '明显缺失'

def explain_text(row: dict, tags: list[dict], status: str) -> str:
    names = ' '.join([t['tag_name'] for t in tags if t.get('tag_type') == 'negative'])
    if status == '结构完整':
        return f"该标的在{row.get('signal_period','30m')}周期出现2560结构，价格接近MA25，MA25趋势正常，量能结构满足，当前结构状态为"结构完整"。"
    return f"该标的出现2560相关结构，但存在{names}，当前结构状态为"{status}"。"
```

#### `app/services/signal_engine_2560.py` — 2560 核心信号引擎

```python
import hashlib
import json
import time
from datetime import datetime
from typing import Optional
import pandas as pd
from app.db.repository import KlineRepository
from app.services.config_service import ConfigService
from app.services.indicator_engine import enrich_indicators, to_indicator_rows
from app.services.tag_service import build_tags, structure_status, explain_text

class SignalEngine2560:
    def __init__(self, db, strategy_version: str = '2.4.0'):
        self.db = db
        self.repo = KlineRepository(db)
        self.strategy_version = strategy_version

    @staticmethod
    def day(value: int) -> int:
        return int(str(int(value))[:8])

    def uid(self, code: str, signal_time: int, period: str) -> str:
        return hashlib.md5(f'{code}|{signal_time}|{period}|{self.strategy_version}'.encode()).hexdigest()

    def run(self, codes: Optional[list[str]] = None, source: Optional[str] = None, limit: Optional[int] = None, commit_every: int = 50) -> dict:
        cfg = ConfigService(self.db).load_strategy_config()
        batch_id = int(time.strftime('%Y%m%d%H%M%S'))
        self.repo.insert_batch({'batch_id': batch_id, 'batch_name': f'S2560-{batch_id}', 'run_time': datetime.now(), 'data_source': source, 'strategy_code': 'S2560', 'strategy_version': self.strategy_version, 'param_snapshot': json.dumps(cfg, ensure_ascii=False), 'status': 'running', 'message': 'started'})
        self.db.commit()
        all_codes = codes or self.repo.list_codes(source=source, limit=limit)
        processed = 0
        signals = 0
        errors = []
        for code in all_codes:
            try:
                info = self.repo.get_stock_info(code)
                name = (info.get('name') or '').upper()
                if 'ST' in name:
                    processed += 1
                    continue
                daily = self.repo.read_daily(code, source=source, lookback=320)
                m30 = self.repo.read_minute(code, '30m', source=source, lookback=3000)
                m5 = self.repo.read_minute(code, '5m', source=source, lookback=6000)
                if daily.empty or m30.empty:
                    processed += 1
                    continue
                daily_i = enrich_indicators(daily, 'daily', source, cfg)
                m30_i = enrich_indicators(m30, '30m', source, cfg)
                m5_i = enrich_indicators(m5, '5m', source, cfg) if not m5.empty else pd.DataFrame()
                self.repo.upsert_indicators(to_indicator_rows(daily_i.tail(260)))
                self.repo.upsert_indicators(to_indicator_rows(m30_i.tail(1200)))
                if not m5_i.empty:
                    self.repo.upsert_indicators(to_indicator_rows(m5_i.tail(1200)))
                signals += self.scan(code, info, daily_i, m30_i, m5_i, cfg, batch_id, source)
                processed += 1
                if processed % commit_every == 0:
                    self.db.commit()
            except Exception as exc:
                self.db.rollback()
                errors.append(f'{code}: {exc}')
                processed += 1
        self.repo.update_batch_status(batch_id, 'success', f'processed={processed}, signals={signals}, errors={len(errors)}')
        self.db.commit()
        return {'batch_id': batch_id, 'processed': processed, 'signals': signals, 'errors': errors[:20]}

    def prev_daily(self, daily_i: pd.DataFrame, signal_time: int):
        subset = daily_i[daily_i['date'] < self.day(signal_time)]
        return None if subset.empty else subset.iloc[-1]

    def confirm5(self, m5_i: pd.DataFrame, signal_time: int, cfg: dict):
        if m5_i.empty:
            return False, False
        window = m5_i[m5_i['date'] <= signal_time].tail(6)
        if window.empty:
            return False, False
        last = window.iloc[-1]
        pull = bool(pd.notna(last.get('ma25')) and (last['close'] >= last['ma25'] or abs(last.get('price_ma25_deviation_pct', 999)) <= float(cfg.get('pullback_threshold_pct', 2.0))))
        bullish = bool((window.tail(2)['close'] > window.tail(2)['open']).any())
        return pull, bullish

    def scan(self, code, info, daily_i, m30_i, m5_i, cfg, batch_id, source):
        count = 0
        threshold = float(cfg.get('pullback_threshold_pct', 2.0))
        min_volume = float(cfg.get('min_volume_ratio', 1.0))
        slope_threshold = float(cfg.get('ma_slope_medium_threshold', 0.0))
        cooldown = int(cfg.get('signal_cooldown_days', 3))
        last_day = None
        for _, r in m30_i.tail(600).iterrows():
            if pd.isna(r.get('ma25')) or pd.isna(r.get('vol_ma60')):
                continue
            signal_time = int(r['date'])
            signal_day = self.day(signal_time)
            if last_day and signal_day - last_day < cooldown:
                continue
            price_near = abs(r.get('price_ma25_deviation_pct', 999)) <= threshold
            slope_ok = (r.get('ma25_slope_3') if pd.notna(r.get('ma25_slope_3')) else -999) >= slope_threshold
            volume_ok = (r.get('vol_ratio') if pd.notna(r.get('vol_ratio')) else 0) >= min_volume or r.get('vol_ma5_cross_vol_ma60') == 1
            abnormal_ok = r.get('is_abnormal_bar', 1) == 0
            if not (price_near and slope_ok and volume_ok and abnormal_ok):
                continue
            daily_prev = self.prev_daily(daily_i, signal_time)
            trend_price = trend_slope = volatility = False
            data_quality = 'missing'
            if daily_prev is not None:
                ma = daily_prev.get('ma60') if pd.notna(daily_prev.get('ma60')) else daily_prev.get('ma25')
                sl = daily_prev.get('ma60_slope_3') if pd.notna(daily_prev.get('ma60_slope_3')) else daily_prev.get('ma25_slope_3')
                trend_price = bool(pd.notna(ma) and daily_prev['close'] > ma)
                trend_slope = bool(pd.notna(sl) and sl > slope_threshold)
                volatility = bool(pd.notna(daily_prev.get('atr14')) and pd.notna(daily_prev.get('atr20_avg')) and daily_prev['atr14'] > daily_prev['atr20_avg'] * float(cfg.get('atr_weak_ratio', 0.85)))
                data_quality = 'normal'
            pullback, bullish = self.confirm5(m5_i, signal_time, cfg)
            breakout = bool(pd.notna(r.get('high_20')) and r['close'] > r['high_20'] * float(cfg.get('breakout_threshold', 1.0)))
            near = bool(pd.notna(r.get('high_20')) and r['close'] >= r['high_20'] * float(cfg.get('resistance_threshold', 0.95)))
            row = {'signal_uid': self.uid(code, signal_time, '30m'), 'batch_id': batch_id, 'strategy_code': 'S2560', 'strategy_version': self.strategy_version, 'code': code, 'name': info.get('name'), 'signal_time': signal_time, 'signal_period': '30m', 'price': float(r['close']), 'source': source or r.get('source'), 'stock_status': 'NORMAL', 'has_2560_signal': 1, 'price_near_ma25': int(price_near), 'ma25_slope_ok': int(slope_ok), 'volume_structure_ok': int(volume_ok), 'abnormal_filter_ok': int(abnormal_ok), 'trend_price_ok': int(trend_price), 'trend_slope_ok': int(trend_slope), 'volatility_ok': int(volatility), 'breakout_ok': int(breakout), 'volume_ok': int(volume_ok), 'near_resistance': int(near), 'pullback_ok': int(pullback), 'bullish_confirm': int(bullish), 'data_quality_status': data_quality, 'is_duplicate_signal': 0, 'selected_signal': 1, 'structure_status': '', 'strength_score_raw': 0, 'missing_tags': '', 'missing_tag_count': 0, 'explain_text': ''}
            tags = build_tags(row)
            row['structure_status'] = structure_status(tags)
            row['missing_tags'] = ' '.join(t['tag_name'] for t in tags)
            row['missing_tag_count'] = len([t for t in tags if t.get('tag_type') == 'negative'])
            row['explain_text'] = explain_text(row, tags, row['structure_status'])
            row['strength_score_raw'] = max(0, 2.0 - row['missing_tag_count'] * 0.2)
            analysis_id = self.repo.upsert_analysis(row)
            self.repo.replace_tags(analysis_id, batch_id, code, signal_time, tags)
            last_day = signal_day
            count += 1
        return count
```

#### `app/services/statistics_engine.py` — 统计聚合引擎

```python
from sqlalchemy import text
class StatisticsEngine:
    def __init__(self, db):
        self.db = db
    def rebuild(self, batch_id: int):
        self.db.execute(text('DELETE FROM structure_2560_statistics WHERE batch_id=:b'), {'b': batch_id})
        self.db.execute(text("""
            INSERT INTO structure_2560_statistics (batch_id,stat_date,stat_type,group_key,sample_count)
            SELECT batch_id,COALESCE(MAX(signal_time DIV 1000000),0),'BY_STRUCTURE_STATUS',structure_status,COUNT(*)
            FROM structure_2560_analysis WHERE batch_id=:b GROUP BY batch_id,structure_status
        """), {'b': batch_id})
        self.db.commit()
        return {'batch_id': batch_id, 'status': 'statistics rebuilt'}
```

#### `app/services/future_return_engine.py` — 未来收益引擎 (占位)

```python
class FutureReturnEngine:
    def __init__(self, db):
        self.db = db
    def backfill(self, batch_id=None):
        return {'updated': 0, 'note': 'future return backfill placeholder; enable after confirming trading calendar'}
```

#### `app/services/strategy2560_service.py` — 查询服务层

```python
from sqlalchemy import text

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
        if code: where.append('a.code=:code'); p['code']=code
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
    def data_quality_summary(self):
        return rows(self.db.execute(text('SELECT * FROM data_quality_check ORDER BY check_date DESC,period LIMIT 100')))
```

### 5.6 数据模型

#### `app/schemas/common.py`

```python
from typing import Any, Optional
from pydantic import BaseModel

class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: Optional[str] = None
```

---

## 6. 前端 — WebUI

### 6.1 页面结构 — `app/static/index.html`

单页应用，侧边栏导航 + 主内容区。包含 8 个视图:

| 视图 ID | 名称 | 功能 |
|---------|------|------|
| `overview` | 总览 | 信号统计卡片、标签分布图、最新批次信息 |
| `run` | 入库计算 | 股票选择器、全市场摸底、执行计算 |
| `diagnostics` | 摸底指标 | 诊断面板 (柱状图 + 饼图 + 明细表) |
| `signals` | 信号列表 | 分页信号列表 + 筛选 |
| `complete` | 完整结构 | 结构完整案例及后续收益 |
| `statistics` | 结构统计 | 按各类维度聚合统计 |
| `batches` | 批次管理 | 历史分析批次列表 |
| `quality` | 数据质量 | K 线数据完整性检查 |

### 6.2 前端逻辑 — `app/static/app.js`

- 状态管理: `state` 对象 (当前视图、页码、已选股票、市场类型)
- API 封装: `api()` 统一 fetch + 错误处理
- 视图渲染: 各个 `load*` 函数异步加载数据并渲染表格
- 股票选择器: 搜索、全选、按筛选全选、手动输入
- 诊断面板: 未命中原因柱状图 + conic-gradient 饼图
- 响应式: 移动端适配

### 6.3 样式系统

- `styles.css` — 主样式 (内联压缩格式)
- `styles.diagnostic.css` — 诊断面板样式
- `styles.diagnostic-menu.css` — 诊断菜单样式
- `styles.market-filter.css` — 市场筛选样式
- `styles.market-probe.css` — 摸底面板样式

---

## 7. 运维脚本

### 7.1 数据采集

| 脚本 | 功能 | 关键参数 |
|------|------|----------|
| `import_vipdoc_with_pytdx.py` | 导入通达信 vipdoc 数据 | `--root`, `--start`, `--end`, `--daily`, `--lc5` |
| `fill_recent_with_pytdx_hq.py` | pytdx 实时补最新 K 线 | `--codes`, `--count`, `--periods` |

### 7.2 数据加工

| 脚本 | 功能 | 关键参数 |
|------|------|----------|
| `build_30m_from_5m.py` | 5m → 30m 聚合 | `--start`, `--end`, `--market-type` |
| `rebuild_technical_indicator.py` | 重算技术指标 | `--start`, `--end`, `--market-type`, `--periods` |

### 7.3 策略执行

| 脚本 | 功能 | 关键参数 |
|------|------|----------|
| `run_2560_analysis.py` | 运行 2560 信号扫描 | `--codes`, `--market-type`, `--limit` |
| `rebuild_statistics.py` | 重建统计 | `--batch-id` |
| `backfill_future_returns.py` | 回补未来收益 (占位) | `--batch-id` |
| `apply_schema.py` | 执行建表 DDL | 无 |

### 7.4 一键脚本

| 脚本 | 功能 |
|------|------|
| `daily_update_2560.sh` | 每日全量更新 (5 步: daily→lc5→30m→indicator→2560) |
| `daily_update_incremental.sh` | 每日增量更新 (30 天行情 + 90 天指标) |
| `start_webui.sh` | 启动 FastAPI 服务 |
| `run_with_path.sh` | 带 PATH 启动分析 |

---

## 8. 依赖与环境

### 8.1 Python 依赖 (`requirements.txt`)

```
fastapi==0.111.0
uvicorn[standard]==0.30.1
SQLAlchemy==2.0.30
PyMySQL==1.1.1
pydantic-settings==2.3.4
python-dotenv==1.0.1
pandas==2.2.2
numpy==1.26.4
```

### 8.2 环境变量 (`.env.example`)

```
DB_HOST=192.168.1.254
DB_PORT=3306
DB_USER=watchlist_decision_support
DB_PASSWORD=PLEASE_SET_REAL_PASSWORD
DB_NAME=watchlist_decision_support
DB_POOL_SIZE=20
APP_HOST=0.0.0.0
APP_PORT=8000
APP_ENV=local
```

### 8.3 外部依赖

- **MySQL 8.x** — 主数据库
- **pytdx** — 通达信数据接口 (可选，用于实时补数据)
- **通达信 vipdoc** — 本地 K 线数据目录 (`/mnt/e/zd_ciccwm/vipdoc`)

---

## 9. 日常运维指南

### 9.1 每日增量更新 (推荐)

```bash
bash scripts/daily_update_incremental.sh
```

执行流程:
1. 导入最近 30 天日线 (sh/sz 并发)
2. 导入最近 30 天 5m 线 (sh/sz 并发)
3. 5m → 30m 聚合 (串行)
4. 重算最近 90 天指标 (sh/sz 并发)
5. 运行 2560 分析 (sh/sz 并发)

### 9.2 每日全量更新

```bash
bash scripts/daily_update_2560.sh
```

同上，但时间窗口从 2025-10-01 开始 (全量)。

### 9.3 启动 WebUI

```bash
bash scripts/start_webui.sh
# 或手动启动:
export PYTHONPATH=$PWD
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问:
- WebUI: `http://localhost:8000`
- API 文档: `http://localhost:8000/docs`

### 9.4 手动执行 2560 分析

```bash
# 全市场
python scripts/run_2560_analysis.py --market-type all

# 仅沪市
python scripts/run_2560_analysis.py --market-type sh

# 指定股票
python scripts/run_2560_analysis.py --codes sh.600000,sz.000001

# 限制数量
python scripts/run_2560_analysis.py --limit 20
```

### 9.5 系统健康检查

```bash
python -c "from app.db.session import ping_database; print(ping_database())"
```

---

---

## 附录 A — 全部 Python 源码

### A.1 `app/__init__.py`

（空文件，标记为 Python 包）

### A.2 `app/core/__init__.py`

（空文件）

### A.3 `app/db/__init__.py`

（空文件）

### A.4 `app/api/__init__.py`

（空文件）

### A.5 `app/schemas/__init__.py`

（空文件）

### A.6 `app/services/__init__.py`

（空文件）

---

### A.7 `app/main.py` — 应用入口

```python
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
```

---

### A.8 `app/core/config.py` — 环境变量管理

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_HOST: str = '192.168.1.254'
    DB_PORT: int = 3306
    DB_USER: str = 'watchlist_decision_support'
    DB_PASSWORD: str = ''
    DB_NAME: str = 'watchlist_decision_support'
    DB_POOL_SIZE: int = 20
    APP_HOST: str = '0.0.0.0'
    APP_PORT: int = 8000
    APP_ENV: str = 'local'
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    @property
    def sqlalchemy_url(self) -> str:
        return f'mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4'

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

### A.9 `app/db/session.py` — 数据库连接

```python
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()
engine = create_engine(
    settings.sqlalchemy_url,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=max(settings.DB_POOL_SIZE, 10),
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ping_database() -> bool:
    with engine.connect() as conn:
        return conn.execute(text('SELECT 1')).scalar_one() == 1
```

---

### A.10 `app/db/repository.py` — 数据访问层

```python
from __future__ import annotations
from typing import Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

class KlineRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_codes(self, source: Optional[str] = None, limit: Optional[int] = None) -> list[str]:
        sql = 'SELECT code FROM stock_info'
        params = {}
        if source:
            sql += ' WHERE source=:source'
            params['source'] = source
        sql += ' ORDER BY code'
        if limit:
            sql += ' LIMIT :limit'
            params['limit'] = limit
        return [r[0] for r in self.db.execute(text(sql), params).all()]

    def get_stock_info(self, code: str) -> dict:
        row = self.db.execute(text('SELECT * FROM stock_info WHERE code=:code'), {'code': code}).mappings().first()
        return dict(row) if row else {'code': code, 'name': None}

    def read_daily(self, code: str, source: Optional[str] = None, lookback: Optional[int] = None) -> pd.DataFrame:
        sql = 'SELECT code,date,open,high,low,close,volume,amount,source FROM daily_kline WHERE code=:code'
        params = {'code': code}
        if source:
            sql += ' AND source=:source'
            params['source'] = source
        sql += ' ORDER BY date'
        df = pd.read_sql(text(sql), self.db.bind, params=params)
        return df.tail(lookback).reset_index(drop=True) if lookback else df.reset_index(drop=True)

    def read_minute(self, code: str, period: str, source: Optional[str] = None, lookback: Optional[int] = None) -> pd.DataFrame:
        params = {'code': code, 'period': period}
        sf = ''
        if source:
            params['source'] = source
            sf = ' AND source=:source'
        try:
            df = pd.read_sql(text(f"""
                SELECT code,date,period,open,high,low,close,volume,amount,source
                FROM minute_kline_period
                WHERE code=:code AND period=:period {sf}
                ORDER BY date
            """), self.db.bind, params=params)
        except Exception:
            df = pd.DataFrame()
        if df.empty and period == '5m':
            params = {'code': code}
            sf = ''
            if source:
                params['source'] = source
                sf = ' AND source=:source'
            df = pd.read_sql(text(f"""
                SELECT code,date,'5m' AS period,open,high,low,close,volume,amount,source
                FROM minute_kline
                WHERE code=:code {sf}
                ORDER BY date
            """), self.db.bind, params=params)
        return df.tail(lookback).reset_index(drop=True) if lookback and not df.empty else df.reset_index(drop=True)

    def upsert_indicators(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.db.execute(text("""
            INSERT INTO technical_indicator
            (code,period,date,source,stock_status,is_st,ma25,ma60,ma200,ma25_slope_3,ma60_slope_3,atr14,atr20_avg,vol_ma5,vol_ma60,vol_ratio,vol_ma5_cross_vol_ma60,price_ma25_deviation_pct,high_20,low_20,low_30,resistance_level,is_abnormal_bar,data_quality_status)
            VALUES
            (:code,:period,:date,:source,:stock_status,:is_st,:ma25,:ma60,:ma200,:ma25_slope_3,:ma60_slope_3,:atr14,:atr20_avg,:vol_ma5,:vol_ma60,:vol_ratio,:vol_ma5_cross_vol_ma60,:price_ma25_deviation_pct,:high_20,:low_20,:low_30,:resistance_level,:is_abnormal_bar,:data_quality_status)
            ON DUPLICATE KEY UPDATE
            ma25=VALUES(ma25),ma60=VALUES(ma60),ma200=VALUES(ma200),ma25_slope_3=VALUES(ma25_slope_3),ma60_slope_3=VALUES(ma60_slope_3),atr14=VALUES(atr14),atr20_avg=VALUES(atr20_avg),vol_ma5=VALUES(vol_ma5),vol_ma60=VALUES(vol_ma60),vol_ratio=VALUES(vol_ratio),vol_ma5_cross_vol_ma60=VALUES(vol_ma5_cross_vol_ma60),price_ma25_deviation_pct=VALUES(price_ma25_deviation_pct),high_20=VALUES(high_20),low_20=VALUES(low_20),low_30=VALUES(low_30),resistance_level=VALUES(resistance_level),is_abnormal_bar=VALUES(is_abnormal_bar),data_quality_status=VALUES(data_quality_status),updated_at=CURRENT_TIMESTAMP
        """), rows)

    def insert_batch(self, batch: dict) -> None:
        self.db.execute(text("""
            INSERT INTO analysis_batch (batch_id,batch_name,run_time,data_source,strategy_code,strategy_version,param_snapshot,status,message)
            VALUES (:batch_id,:batch_name,:run_time,:data_source,:strategy_code,:strategy_version,:param_snapshot,:status,:message)
            ON DUPLICATE KEY UPDATE status=VALUES(status), message=VALUES(message), updated_at=CURRENT_TIMESTAMP
        """), batch)

    def update_batch_status(self, batch_id: int, status: str, message: str = '') -> None:
        self.db.execute(text('UPDATE analysis_batch SET status=:status,message=:message WHERE batch_id=:batch_id'), {'batch_id': batch_id, 'status': status, 'message': message})

    def upsert_analysis(self, row: dict) -> int:
        self.db.execute(text("""
            INSERT INTO structure_2560_analysis
            (signal_uid,batch_id,strategy_code,strategy_version,code,name,signal_time,signal_period,price,source,stock_status,has_2560_signal,price_near_ma25,ma25_slope_ok,volume_structure_ok,abnormal_filter_ok,trend_price_ok,trend_slope_ok,volatility_ok,breakout_ok,volume_ok,near_resistance,pullback_ok,bullish_confirm,structure_status,strength_score_raw,missing_tags,missing_tag_count,explain_text,data_quality_status,is_duplicate_signal,selected_signal)
            VALUES
            (:signal_uid,:batch_id,:strategy_code,:strategy_version,:code,:name,:signal_time,:signal_period,:price,:source,:stock_status,:has_2560_signal,:price_near_ma25,:ma25_slope_ok,:volume_structure_ok,:abnormal_filter_ok,:trend_price_ok,:trend_slope_ok,:volatility_ok,:breakout_ok,:volume_ok,:near_resistance,:pullback_ok,:bullish_confirm,:structure_status,:strength_score_raw,:missing_tags,:missing_tag_count,:explain_text,:data_quality_status,:is_duplicate_signal,:selected_signal)
            ON DUPLICATE KEY UPDATE
            batch_id=VALUES(batch_id),name=VALUES(name),price=VALUES(price),structure_status=VALUES(structure_status),strength_score_raw=VALUES(strength_score_raw),missing_tags=VALUES(missing_tags),missing_tag_count=VALUES(missing_tag_count),explain_text=VALUES(explain_text),data_quality_status=VALUES(data_quality_status),updated_at=CURRENT_TIMESTAMP
        """), row)
        return int(self.db.execute(text('SELECT id FROM structure_2560_analysis WHERE signal_uid=:uid'), {'uid': row['signal_uid']}).scalar_one())

    def replace_tags(self, analysis_id: int, batch_id: int, code: str, signal_time: int, tags: list[dict]) -> None:
        self.db.execute(text('DELETE FROM structure_2560_tag_detail WHERE analysis_id=:id'), {'id': analysis_id})
        if not tags:
            return
        rows = [{'analysis_id': analysis_id, 'batch_id': batch_id, 'code': code, 'signal_time': signal_time, **t} for t in tags]
        self.db.execute(text("""
            INSERT INTO structure_2560_tag_detail (analysis_id,batch_id,code,signal_time,tag_code,tag_name,tag_type)
            VALUES (:analysis_id,:batch_id,:code,:signal_time,:tag_code,:tag_name,:tag_type)
        """), rows)
```

---

### A.11 `app/schemas/common.py` — 响应模型

```python
from typing import Any, Optional
from pydantic import BaseModel

class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: Optional[str] = None
```

---

### A.12 `app/api/strategy2560.py` — 2560 策略路由

```python
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
```

---

### A.13 `app/api/data_quality.py` — 数据质量路由

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.services.strategy2560_service import Strategy2560Service

router = APIRouter(prefix='/api/data-quality', tags=['data-quality'])

@router.get('/summary', response_model=ApiResponse)
def summary(db: Session = Depends(get_db)):
    return ApiResponse(data=Strategy2560Service(db).data_quality_summary())
```

---

### A.14 `app/services/config_service.py` — 策略参数服务

```python
from __future__ import annotations
from typing import Any, Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_CONFIG: dict[str, Any] = {
    'ma_price_period': 25,
    'vol_short_period': 5,
    'vol_long_period': 60,
    'pullback_threshold_pct': 2.0,
    'min_volume_ratio': 1.0,
    'resistance_threshold': 0.95,
    'breakout_threshold': 1.0,
    'atr_period': 14,
    'atr_compare_period': 20,
    'atr_weak_ratio': 0.85,
    'breakout_period': 20,
    'signal_cooldown_days': 3,
    'ma_slope_medium_threshold': 0.0,
}

def _cast(value: str, value_type: str):
    if value_type == 'int':
        return int(float(value))
    if value_type == 'double':
        return float(value)
    if value_type == 'bool':
        return str(value).lower() in {'1','true','yes','y'}
    return value

class ConfigService:
    def __init__(self, db: Session):
        self.db = db

    def load_strategy_config(self, strategy_code: str = 'S2560') -> dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        try:
            rows = self.db.execute(text('SELECT config_key,config_value,value_type FROM strategy_config WHERE strategy_code=:s AND enabled=1'), {'s': strategy_code}).mappings().all()
            for r in rows:
                cfg[r['config_key']] = _cast(r['config_value'], r['value_type'])
        except Exception:
            pass
        return cfg
```

---

### A.15 `app/services/indicator_engine.py` — 技术指标计算

```python
import numpy as np
import pandas as pd

def slope_pct(series: pd.Series, periods: int = 3) -> pd.Series:
    prev = series.shift(periods)
    return (series - prev) / prev.replace(0, np.nan) * 100.0

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df['close'].shift(1)
    tr = pd.concat([(df['high']-df['low']), (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def enrich_indicators(df: pd.DataFrame, period: str, source: str | None, cfg: dict, stock_status: str = 'NORMAL', is_st: int = 0) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy().sort_values('date').reset_index(drop=True)
    out['period'] = period
    if 'source' not in out.columns:
        out['source'] = source or 'default'
    for col in ['open','high','low','close','volume','amount']:
        out[col] = pd.to_numeric(out[col], errors='coerce')
    ma_period = int(cfg.get('ma_price_period', 25))
    vol_short = int(cfg.get('vol_short_period', 5))
    vol_long = int(cfg.get('vol_long_period', 60))
    atr_period = int(cfg.get('atr_period', 14))
    atr_compare = int(cfg.get('atr_compare_period', 20))
    breakout_period = int(cfg.get('breakout_period', 20))
    out['ma25'] = out['close'].rolling(ma_period, min_periods=ma_period).mean()
    out['ma60'] = out['close'].rolling(60, min_periods=60).mean()
    out['ma200'] = out['close'].rolling(200, min_periods=200).mean()
    out['ma25_slope_3'] = slope_pct(out['ma25'])
    out['ma60_slope_3'] = slope_pct(out['ma60'])
    out['atr14'] = atr(out, atr_period)
    out['atr20_avg'] = out['atr14'].rolling(atr_compare, min_periods=atr_compare).mean()
    out['vol_ma5'] = out['volume'].rolling(vol_short, min_periods=vol_short).mean()
    out['vol_ma60'] = out['volume'].rolling(vol_long, min_periods=vol_long).mean()
    out['vol_ratio'] = out['vol_ma5'] / out['vol_ma60'].replace(0, np.nan)
    out['vol_ma5_cross_vol_ma60'] = ((out['vol_ratio'].shift(1) <= 1.0) & (out['vol_ratio'] > 1.0)).astype('Int64')
    out['price_ma25_deviation_pct'] = (out['close'] - out['ma25']) / out['ma25'].replace(0, np.nan) * 100.0
    out['high_20'] = out['high'].shift(1).rolling(breakout_period, min_periods=breakout_period).max()
    out['low_20'] = out['low'].shift(1).rolling(20, min_periods=20).min()
    out['low_30'] = out['low'].shift(1).rolling(30, min_periods=30).min()
    out['resistance_level'] = out['high_20']
    out['is_abnormal_bar'] = (out[['open','high','low','close','volume']].isna().any(axis=1) | ((out['open']==out['high']) & (out['high']==out['low']) & (out['low']==out['close'])) | (out['volume'].fillna(0)<=0)).astype(int)
    out['data_quality_status'] = np.where(out['is_abnormal_bar'] == 1, 'abnormal', 'normal')
    out['stock_status'] = stock_status
    out['is_st'] = is_st
    return out

def to_indicator_rows(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    cols = ['code','period','date','source','stock_status','is_st','ma25','ma60','ma200','ma25_slope_3','ma60_slope_3','atr14','atr20_avg','vol_ma5','vol_ma60','vol_ratio','vol_ma5_cross_vol_ma60','price_ma25_deviation_pct','high_20','low_20','low_30','resistance_level','is_abnormal_bar','data_quality_status']
    return df[cols].replace({np.nan: None}).to_dict('records')
```

---

### A.16 `app/services/tag_service.py` — 标签体系

```python
TAG = {
    'LACK_VOLUME': '#缺量',
    'HIGH_POSITION': '#高位',
    'SIDEWAYS': '#震荡',
    'NO_BREAKOUT': '#未突破',
    'AGAINST_TREND': '#逆势',
    'WEAK_TREND': '#趋势走弱',
    'NO_CONFIRM': '#未确认',
    'PRICE_AWAY_MA25': '#偏离MA25',
    'MA25_WEAK': '#MA25走弱',
    'DATA_INSUFFICIENT': '#数据不足',
    'COMPLETE_STRUCTURE': '#结构完整',
}

def build_tags(row: dict) -> list[dict]:
    tags = []
    def add(code, tag_type='negative'):
        tags.append({'tag_code': code, 'tag_name': TAG[code], 'tag_type': tag_type})
    if not row.get('volume_ok') or not row.get('volume_structure_ok'):
        add('LACK_VOLUME')
    if row.get('near_resistance'):
        add('HIGH_POSITION')
    if not row.get('volatility_ok'):
        add('SIDEWAYS')
    if not row.get('breakout_ok'):
        add('NO_BREAKOUT')
    if not row.get('trend_price_ok'):
        add('AGAINST_TREND')
    if not row.get('trend_slope_ok'):
        add('WEAK_TREND')
    if not row.get('pullback_ok') or not row.get('bullish_confirm'):
        add('NO_CONFIRM')
    if not row.get('price_near_ma25'):
        add('PRICE_AWAY_MA25')
    if not row.get('ma25_slope_ok'):
        add('MA25_WEAK')
    if row.get('data_quality_status') != 'normal':
        add('DATA_INSUFFICIENT')
    if not tags:
        add('COMPLETE_STRUCTURE', 'positive')
    return tags

def structure_status(tags: list[dict]) -> str:
    neg = len([t for t in tags if t.get('tag_type') == 'negative'])
    if any(t['tag_code'] == 'DATA_INSUFFICIENT' for t in tags):
        return '数据不足'
    if neg == 0:
        return '结构完整'
    if neg <= 2:
        return '部分满足'
    return '明显缺失'

def explain_text(row: dict, tags: list[dict], status: str) -> str:
    names = ' '.join([t['tag_name'] for t in tags if t.get('tag_type') == 'negative'])
    if status == '结构完整':
        return f"该标的在{row.get('signal_period','30m')}周期出现2560结构，价格接近MA25，MA25趋势正常，量能结构满足，当前结构状态为"结构完整"。"
    return f"该标的出现2560相关结构，但存在{names}，当前结构状态为"{status}"。"
```

---

### A.17 `app/services/signal_engine_2560.py` — 2560 核心信号引擎

```python
import hashlib
import json
import time
from datetime import datetime
from typing import Optional
import pandas as pd
from app.db.repository import KlineRepository
from app.services.config_service import ConfigService
from app.services.indicator_engine import enrich_indicators, to_indicator_rows
from app.services.tag_service import build_tags, structure_status, explain_text

class SignalEngine2560:
    def __init__(self, db, strategy_version: str = '2.4.0'):
        self.db = db
        self.repo = KlineRepository(db)
        self.strategy_version = strategy_version

    @staticmethod
    def day(value: int) -> int:
        return int(str(int(value))[:8])

    def uid(self, code: str, signal_time: int, period: str) -> str:
        return hashlib.md5(f'{code}|{signal_time}|{period}|{self.strategy_version}'.encode()).hexdigest()

    def run(self, codes: Optional[list[str]] = None, source: Optional[str] = None, limit: Optional[int] = None, commit_every: int = 50) -> dict:
        cfg = ConfigService(self.db).load_strategy_config()
        batch_id = int(time.strftime('%Y%m%d%H%M%S'))
        self.repo.insert_batch({'batch_id': batch_id, 'batch_name': f'S2560-{batch_id}', 'run_time': datetime.now(), 'data_source': source, 'strategy_code': 'S2560', 'strategy_version': self.strategy_version, 'param_snapshot': json.dumps(cfg, ensure_ascii=False), 'status': 'running', 'message': 'started'})
        self.db.commit()
        all_codes = codes or self.repo.list_codes(source=source, limit=limit)
        processed = 0
        signals = 0
        errors = []
        for code in all_codes:
            try:
                info = self.repo.get_stock_info(code)
                name = (info.get('name') or '').upper()
                if 'ST' in name:
                    processed += 1
                    continue
                daily = self.repo.read_daily(code, source=source, lookback=320)
                m30 = self.repo.read_minute(code, '30m', source=source, lookback=3000)
                m5 = self.repo.read_minute(code, '5m', source=source, lookback=6000)
                if daily.empty or m30.empty:
                    processed += 1
                    continue
                daily_i = enrich_indicators(daily, 'daily', source, cfg)
                m30_i = enrich_indicators(m30, '30m', source, cfg)
                m5_i = enrich_indicators(m5, '5m', source, cfg) if not m5.empty else pd.DataFrame()
                self.repo.upsert_indicators(to_indicator_rows(daily_i.tail(260)))
                self.repo.upsert_indicators(to_indicator_rows(m30_i.tail(1200)))
                if not m5_i.empty:
                    self.repo.upsert_indicators(to_indicator_rows(m5_i.tail(1200)))
                signals += self.scan(code, info, daily_i, m30_i, m5_i, cfg, batch_id, source)
                processed += 1
                if processed % commit_every == 0:
                    self.db.commit()
            except Exception as exc:
                self.db.rollback()
                errors.append(f'{code}: {exc}')
                processed += 1
        self.repo.update_batch_status(batch_id, 'success', f'processed={processed}, signals={signals}, errors={len(errors)}')
        self.db.commit()
        return {'batch_id': batch_id, 'processed': processed, 'signals': signals, 'errors': errors[:20]}

    def prev_daily(self, daily_i: pd.DataFrame, signal_time: int):
        subset = daily_i[daily_i['date'] < self.day(signal_time)]
        return None if subset.empty else subset.iloc[-1]

    def confirm5(self, m5_i: pd.DataFrame, signal_time: int, cfg: dict):
        if m5_i.empty:
            return False, False
        window = m5_i[m5_i['date'] <= signal_time].tail(6)
        if window.empty:
            return False, False
        last = window.iloc[-1]
        pull = bool(pd.notna(last.get('ma25')) and (last['close'] >= last['ma25'] or abs(last.get('price_ma25_deviation_pct', 999)) <= float(cfg.get('pullback_threshold_pct', 2.0))))
        bullish = bool((window.tail(2)['close'] > window.tail(2)['open']).any())
        return pull, bullish

    def scan(self, code, info, daily_i, m30_i, m5_i, cfg, batch_id, source):
        count = 0
        threshold = float(cfg.get('pullback_threshold_pct', 2.0))
        min_volume = float(cfg.get('min_volume_ratio', 1.0))
        slope_threshold = float(cfg.get('ma_slope_medium_threshold', 0.0))
        cooldown = int(cfg.get('signal_cooldown_days', 3))
        last_day = None
        for _, r in m30_i.tail(600).iterrows():
            if pd.isna(r.get('ma25')) or pd.isna(r.get('vol_ma60')):
                continue
            signal_time = int(r['date'])
            signal_day = self.day(signal_time)
            if last_day and signal_day - last_day < cooldown:
                continue
            price_near = abs(r.get('price_ma25_deviation_pct', 999)) <= threshold
            slope_ok = (r.get('ma25_slope_3') if pd.notna(r.get('ma25_slope_3')) else -999) >= slope_threshold
            volume_ok = (r.get('vol_ratio') if pd.notna(r.get('vol_ratio')) else 0) >= min_volume or r.get('vol_ma5_cross_vol_ma60') == 1
            abnormal_ok = r.get('is_abnormal_bar', 1) == 0
            if not (price_near and slope_ok and volume_ok and abnormal_ok):
                continue
            daily_prev = self.prev_daily(daily_i, signal_time)
            trend_price = trend_slope = volatility = False
            data_quality = 'missing'
            if daily_prev is not None:
                ma = daily_prev.get('ma60') if pd.notna(daily_prev.get('ma60')) else daily_prev.get('ma25')
                sl = daily_prev.get('ma60_slope_3') if pd.notna(daily_prev.get('ma60_slope_3')) else daily_prev.get('ma25_slope_3')
                trend_price = bool(pd.notna(ma) and daily_prev['close'] > ma)
                trend_slope = bool(pd.notna(sl) and sl > slope_threshold)
                volatility = bool(pd.notna(daily_prev.get('atr14')) and pd.notna(daily_prev.get('atr20_avg')) and daily_prev['atr14'] > daily_prev['atr20_avg'] * float(cfg.get('atr_weak_ratio', 0.85)))
                data_quality = 'normal'
            pullback, bullish = self.confirm5(m5_i, signal_time, cfg)
            breakout = bool(pd.notna(r.get('high_20')) and r['close'] > r['high_20'] * float(cfg.get('breakout_threshold', 1.0)))
            near = bool(pd.notna(r.get('high_20')) and r['close'] >= r['high_20'] * float(cfg.get('resistance_threshold', 0.95)))
            row = {'signal_uid': self.uid(code, signal_time, '30m'), 'batch_id': batch_id, 'strategy_code': 'S2560', 'strategy_version': self.strategy_version, 'code': code, 'name': info.get('name'), 'signal_time': signal_time, 'signal_period': '30m', 'price': float(r['close']), 'source': source or r.get('source'), 'stock_status': 'NORMAL', 'has_2560_signal': 1, 'price_near_ma25': int(price_near), 'ma25_slope_ok': int(slope_ok), 'volume_structure_ok': int(volume_ok), 'abnormal_filter_ok': int(abnormal_ok), 'trend_price_ok': int(trend_price), 'trend_slope_ok': int(trend_slope), 'volatility_ok': int(volatility), 'breakout_ok': int(breakout), 'volume_ok': int(volume_ok), 'near_resistance': int(near), 'pullback_ok': int(pullback), 'bullish_confirm': int(bullish), 'data_quality_status': data_quality, 'is_duplicate_signal': 0, 'selected_signal': 1, 'structure_status': '', 'strength_score_raw': 0, 'missing_tags': '', 'missing_tag_count': 0, 'explain_text': ''}
            tags = build_tags(row)
            row['structure_status'] = structure_status(tags)
            row['missing_tags'] = ' '.join(t['tag_name'] for t in tags)
            row['missing_tag_count'] = len([t for t in tags if t.get('tag_type') == 'negative'])
            row['explain_text'] = explain_text(row, tags, row['structure_status'])
            row['strength_score_raw'] = max(0, 2.0 - row['missing_tag_count'] * 0.2)
            analysis_id = self.repo.upsert_analysis(row)
            self.repo.replace_tags(analysis_id, batch_id, code, signal_time, tags)
            last_day = signal_day
            count += 1
        return count
```

---

### A.18 `app/services/statistics_engine.py` — 统计聚合引擎

```python
from sqlalchemy import text
class StatisticsEngine:
    def __init__(self, db):
        self.db = db
    def rebuild(self, batch_id: int):
        self.db.execute(text('DELETE FROM structure_2560_statistics WHERE batch_id=:b'), {'b': batch_id})
        self.db.execute(text("""
            INSERT INTO structure_2560_statistics (batch_id,stat_date,stat_type,group_key,sample_count)
            SELECT batch_id,COALESCE(MAX(signal_time DIV 1000000),0),'BY_STRUCTURE_STATUS',structure_status,COUNT(*)
            FROM structure_2560_analysis WHERE batch_id=:b GROUP BY batch_id,structure_status
        """), {'b': batch_id})
        self.db.commit()
        return {'batch_id': batch_id, 'status': 'statistics rebuilt'}
```

---

### A.19 `app/services/future_return_engine.py` — 未来收益引擎 (占位)

```python
class FutureReturnEngine:
    def __init__(self, db):
        self.db = db
    def backfill(self, batch_id=None):
        return {'updated': 0, 'note': 'future return backfill placeholder; enable after confirming trading calendar'}
```

---

### A.20 `app/services/strategy2560_service.py` — 查询服务层

```python
from sqlalchemy import text

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
        if code: where.append('a.code=:code'); p['code']=code
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
    def data_quality_summary(self):
        return rows(self.db.execute(text('SELECT * FROM data_quality_check ORDER BY check_date DESC,period LIMIT 100')))
```

---

### A.21 `scripts/apply_schema.py` — 建表脚本

```python
from pathlib import Path
from sqlalchemy import create_engine, text
from app.core.config import get_settings

def split_sql(sql: str):
    parts = []
    buf = []
    in_single = False
    in_double = False
    for ch in sql:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == ';' and not in_single and not in_double:
            stmt = ''.join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
        else:
            buf.append(ch)
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return parts

def main():
    sql_path = Path('sql/2560_schema_v2.4.sql')
    if not sql_path.exists():
        raise FileNotFoundError(sql_path)
    engine = create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True, future=True)
    sql = sql_path.read_text(encoding='utf-8')
    statements = [s for s in split_sql(sql) if s.strip() and not s.strip().startswith('--')]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    print(f'已执行 SQL 语句数量: {len(statements)}')

if __name__ == '__main__':
    main()
```

---

### A.22 `scripts/import_vipdoc_with_pytdx.py` — 导入通达信数据

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_vipdoc_with_pytdx.py

功能：
- 导入中金/通达信 vipdoc 本地数据
- 支持 daily (.day)
- 支持 5m (.lc5, fzline)
- date 使用 BIGINT
- 自动跳过 Unknown security type
- 重复执行 = 覆盖更新（先删后插）

依赖：
pip install pytdx pandas sqlalchemy pymysql
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import pandas as pd
from sqlalchemy import text

from pytdx.reader import TdxDailyBarReader, TdxLCMinBarReader
from app.db.session import SessionLocal


# ------------------------
# 参数解析
# ------------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, help="vipdoc 根目录")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--daily", action="store_true")
    p.add_argument("--lc5", action="store_true")
    p.add_argument("--markets", default="sh,sz")
    p.add_argument("--limit-files", type=int)
    return p.parse_args()


# ------------------------
# 工具函数
# ------------------------
def code_from_filename(path: Path, market: str) -> str:
    name = path.stem.lower()
    digits = "".join(c for c in name if c.isdigit())
    return f"{market}.{digits[-6:]}"


def day_int(dt) -> int:
    return int(pd.to_datetime(dt).strftime("%Y%m%d"))


def minute_int(dt) -> int:
    return int(pd.to_datetime(dt).strftime("%Y%m%d%H%M%S"))


# ------------------------
# daily 导入
# ------------------------
def import_daily(db, reader, path: Path, market: str, start, end):
    code = code_from_filename(path, market)

    try:
        df = reader.get_df(str(path))
    except Exception as e:
        if "Unknown security type" in str(e):
            print(f"[daily][SKIP] {path.name}: Unknown security type")
            return 0
        print(f"[daily][ERROR] {path.name}: {e}")
        return 0

    if df is None or df.empty:
        return 0

    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    if df.empty:
        return 0

    start_i = day_int(start)
    end_i = day_int(end)

    db.execute(
        text("""
            DELETE FROM daily_kline
            WHERE code=:code AND date BETWEEN :s AND :e
        """),
        {"code": code, "s": start_i, "e": end_i},
    )

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "code": code,
            "date": day_int(r["date"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r.get("volume", 0) or 0),
            "amount": float(r.get("amount", 0) or 0),
            "source": "pytdx_day",
        })

    if rows:
        db.execute(
            text("""
                INSERT INTO daily_kline
                (code,date,open,high,low,close,volume,amount,source)
                VALUES
                (:code,:date,:open,:high,:low,:close,:volume,:amount,:source)
            """),
            rows,
        )

    return len(rows)


# ------------------------
# lc5 导入
# ------------------------
def import_lc5(db, reader, path: Path, market: str, start, end):
    code = code_from_filename(path, market)

    try:
        df = reader.get_df(str(path))
    except Exception as e:
        if "Unknown security type" in str(e):
            print(f"[lc5][SKIP] {path.name}: Unknown security type")
            return 0
        print(f"[lc5][ERROR] {path.name}: {e}")
        return 0

    if df is None or df.empty:
        return 0

    df = df.reset_index()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df[(df["datetime"] >= start) & (df["datetime"] <= end)]
    if df.empty:
        return 0

    start_i = minute_int(pd.to_datetime(start))
    end_i = minute_int(pd.to_datetime(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))

    db.execute(
        text("""
            DELETE FROM minute_kline_period
            WHERE code=:code AND period='5m' AND date BETWEEN :s AND :e
        """),
        {"code": code, "s": start_i, "e": end_i},
    )

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "code": code,
            "period": "5m",
            "date": minute_int(r["datetime"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r.get("volume", 0) or 0),
            "amount": float(r.get("amount", 0) or 0),
            "source": "pytdx_lc5",
        })

    if rows:
        db.execute(
            text("""
                INSERT INTO minute_kline_period
                (code,period,date,open,high,low,close,volume,amount,source)
                VALUES
                (:code,:period,:date,:open,:high,:low,:close,:volume,:amount,:source)
            """),
            rows,
        )

    return len(rows)


# ------------------------
# 主入口
# ------------------------
def main():
    args = parse_args()

    if not args.daily and not args.lc5:
        print("必须指定 --daily 或 --lc5")
        sys.exit(1)

    root = Path(args.root)
    start = pd.to_datetime(args.start)
    end = pd.to_datetime(args.end)

    markets = [m.strip() for m in args.markets.split(",")]

    daily_reader = TdxDailyBarReader()
    lc5_reader = TdxLCMinBarReader()

    total_daily = 0
    total_lc5 = 0

    with SessionLocal() as db:
        for market in markets:
            if args.daily:
                base = root / market / "lday"
                files = sorted(base.glob("*.day"))
                if args.limit_files:
                    files = files[:args.limit_files]

                for f in files:
                    total_daily += import_daily(db, daily_reader, f, market, start, end)

                db.commit()

            if args.lc5:
                base = root / market / "fzline"
                files = sorted(base.glob("*.lc5"))
                if args.limit_files:
                    files = files[:args.limit_files]

                for f in files:
                    total_lc5 += import_lc5(db, lc5_reader, f, market, start, end)

                db.commit()

    print({
        "daily_rows": total_daily,
        "lc5_rows": total_lc5,
    })


if __name__ == "__main__":
    main()
```

---

### A.23 `scripts/build_30m_from_5m.py` — 5m → 30m 聚合

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 5m 数值型 date(YYYYMMDDHHMMSS) 聚合生成 30m。"""
from __future__ import annotations
import argparse, json
import pandas as pd
from sqlalchemy import inspect, text
from app.db.session import SessionLocal

def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument('--start', required=True)
    p.add_argument('--end', default=None)
    p.add_argument('--market-type', default='all')
    p.add_argument('--limit-codes', type=int, default=None)
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()

def table_columns(db, table): return {c['name'] for c in inspect(db.bind).get_columns(table)}
def start_i(s): return int(pd.to_datetime(s).strftime('%Y%m%d000000'))
def end_i(s): return int(pd.to_datetime(s).strftime('%Y%m%d235959')) if s else None
def date_to_dt(v): return pd.to_datetime(str(int(v)), format='%Y%m%d%H%M%S')
def dt_to_int(v): return int(pd.to_datetime(v).strftime('%Y%m%d%H%M%S'))

def code_where(mt):
    mt=(mt or 'all').lower()
    if mt=='sh': return "code LIKE 'sh.%'"
    if mt=='sz': return "code LIKE 'sz.%'"
    if mt=='sh60': return "code LIKE 'sh.60%'"
    if mt=='sh68': return "code LIKE 'sh.68%'"
    if mt=='sz00': return "code LIKE 'sz.00%'"
    if mt=='sz30': return "code LIKE 'sz.30%'"
    return "(code LIKE 'sh.%' OR code LIKE 'sz.%')"

def bucket_30m(ts):
    ts=pd.to_datetime(ts); d=ts.normalize()
    eps=[d+pd.Timedelta(hours=10),d+pd.Timedelta(hours=10,minutes=30),d+pd.Timedelta(hours=11),d+pd.Timedelta(hours=11,minutes=30),d+pd.Timedelta(hours=13,minutes=30),d+pd.Timedelta(hours=14),d+pd.Timedelta(hours=14,minutes=30),d+pd.Timedelta(hours=15)]
    for ep in eps:
        if ts<=ep: return ep
    return None

def insert_rows(db, rows, dry):
    if not rows: return 0
    cols=table_columns(db,'minute_kline_period'); usable=[k for k in rows[0] if k in cols]
    if dry: return len(rows)
    db.execute(text(f"INSERT INTO minute_kline_period ({','.join(usable)}) VALUES ({','.join(':'+c for c in usable)})"), [{k:r.get(k) for k in usable} for r in rows])
    return len(rows)

def main():
    a=parse_args(); si=start_i(a.start); ei=end_i(a.end); total=0
    with SessionLocal() as db:
        params={'start':si}; ef=''
        if ei: ef=' AND date<=:end'; params['end']=ei
        codes=[r[0] for r in db.execute(text(f"SELECT DISTINCT code FROM minute_kline_period WHERE period='5m' AND date>=:start{ef} AND {code_where(a.market_type)} ORDER BY code"), params).fetchall()]
        if a.limit_codes: codes=codes[:a.limit_codes]
        for i,code in enumerate(codes,1):
            p={'code':code,'start':si}; q="SELECT code,date,open,high,low,close,volume,amount FROM minute_kline_period WHERE code=:code AND period='5m' AND date>=:start"
            if ei: q+=' AND date<=:end'; p['end']=ei
            q+=' ORDER BY date'
            rows=db.execute(text(q),p).mappings().all()
            if not rows: continue
            df=pd.DataFrame([dict(r) for r in rows]); df['dt']=df['date'].map(date_to_dt); df['bucket']=df['dt'].map(bucket_30m); df=df[df['bucket'].notna()]
            out=[]
            for bucket,g in df.groupby('bucket'):
                g=g.sort_values('dt')
                out.append({'code':code,'period':'30m','date':dt_to_int(bucket),'open':float(g.iloc[0]['open']),'high':float(g['high'].max()),'low':float(g['low'].min()),'close':float(g.iloc[-1]['close']),'volume':float(g['volume'].sum()),'amount':float(g['amount'].sum()),'source':'build_from_5m'})
            if not a.dry_run:
                dp={'code':code,'start':si}; del_sql="DELETE FROM minute_kline_period WHERE code=:code AND period='30m' AND date>=:start"
                if ei: del_sql+=' AND date<=:end'; dp['end']=ei
                db.execute(text(del_sql),dp)
            total+=insert_rows(db,out,a.dry_run)
            if i%100==0:
                if not a.dry_run: db.commit()
                print(f"processed code={i}, 30m_rows={total}")
        if not a.dry_run: db.commit()
    print(json.dumps({'codes':len(codes),'inserted_30m_rows':total,'dry_run':a.dry_run}, ensure_ascii=False, indent=2))
if __name__=='__main__': main()
```

---

### A.24 `scripts/rebuild_technical_indicator.py` — 重算技术指标

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重算 technical_indicator：daily / 5m / 30m

修复点：
1. 彻底把 pandas/numpy 的 NaN / inf 转成 None，避免 pymysql: nan can not be used with MySQL
2. 按 code 分批读取和写入，避免一次性把全市场 5m/30m 全读进内存
3. 适配 2560_schema_v2.4：date 为 BIGINT / INT 数值时间

用法：
PYTHONPATH=$PWD python scripts/rebuild_technical_indicator.py --start 2025-10-01 --end 2026-05-06 --market-type sh
"""
from __future__ import annotations

import argparse
import math
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from app.db.session import SessionLocal


def parse_args():
    p = argparse.ArgumentParser(description="Rebuild technical_indicator for daily/5m/30m")
    p.add_argument('--start', required=True, help='YYYY-MM-DD')
    p.add_argument('--end', required=True, help='YYYY-MM-DD')
    p.add_argument('--market-type', default='all', help='all/sh/sz/sh60/sh68/sz00/sz30')
    p.add_argument('--periods', default='daily,5m,30m', help='daily,5m,30m')
    p.add_argument('--limit-codes', type=int, default=None, help='调试用：限制每个周期处理前 N 个 code')
    p.add_argument('--commit-every', type=int, default=50, help='每处理 N 个 code commit 一次')
    return p.parse_args()


def market_where(mt: str) -> str:
    mt = (mt or 'all').lower()
    if mt == 'sh':
        return "code LIKE 'sh.%'"
    if mt == 'sz':
        return "code LIKE 'sz.%'"
    if mt == 'sh60':
        return "code LIKE 'sh.60%'"
    if mt == 'sh68':
        return "code LIKE 'sh.68%'"
    if mt == 'sz00':
        return "code LIKE 'sz.00%'"
    if mt == 'sz30':
        return "code LIKE 'sz.30%'"
    return "(code LIKE 'sh.%' OR code LIKE 'sz.%')"


def daily_start_int(s: str) -> int:
    return int(pd.to_datetime(s).strftime('%Y%m%d'))


def daily_end_int(s: str) -> int:
    return int(pd.to_datetime(s).strftime('%Y%m%d'))


def minute_start_int(s: str) -> int:
    return int(pd.to_datetime(s).strftime('%Y%m%d000000'))


def minute_end_int(s: str) -> int:
    return int(pd.to_datetime(s).strftime('%Y%m%d235959'))


def clean_scalar(v: Any) -> Any:
    """把 pandas/numpy 标量安全转成 MySQL 可接受的 Python 标量。"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, (np.floating, float)):
        vf = float(v)
        if not math.isfinite(vf):
            return None
        return vf
    if isinstance(v, (np.integer, int)):
        return int(v)
    return v


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values('date').copy()
    for c in ['open', 'high', 'low', 'close', 'volume']:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    df['ma25'] = df['close'].rolling(25).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['ma200'] = df['close'].rolling(200).mean()

    df['ma25_slope_3'] = (df['ma25'] - df['ma25'].shift(3)) / df['ma25'].shift(3) * 100
    df['ma60_slope_3'] = (df['ma60'] - df['ma60'].shift(3)) / df['ma60'].shift(3) * 100

    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs(),
    ], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    df['atr20_avg'] = tr.rolling(20).mean()

    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ma60'] = df['volume'].rolling(60).mean()
    df['vol_ratio'] = df['vol_ma5'] / df['vol_ma60']
    df['vol_ma5_cross_vol_ma60'] = ((df['vol_ma5'] >= df['vol_ma60']) & (df['vol_ma5'].shift(1) < df['vol_ma60'].shift(1))).astype('float')

    df['price_ma25_deviation_pct'] = (df['close'] - df['ma25']) / df['ma25'] * 100
    df['high_20'] = df['high'].rolling(20).max()
    df['low_20'] = df['low'].rolling(20).min()
    df['low_30'] = df['low'].rolling(30).min()
    df['resistance_level'] = df['high_20']

    amplitude = (df['high'] - df['low']) / df['close'].replace(0, np.nan) * 100
    df['is_abnormal_bar'] = (amplitude > 20).astype(int)
    df['data_quality_status'] = 'normal'
    df.loc[df[['open', 'high', 'low', 'close']].isna().any(axis=1), 'data_quality_status'] = 'missing'
    return df


def get_period_range(period: str, start: str, end: str):
    if period == 'daily':
        return daily_start_int(start), daily_end_int(end)
    return minute_start_int(start), minute_end_int(end)


def source_table(period: str) -> str:
    return 'daily_kline' if period == 'daily' else 'minute_kline_period'


def get_codes(db, period: str, start_i: int, end_i: int, market_type: str, limit_codes: int | None):
    if period == 'daily':
        sql = f"""
            SELECT DISTINCT code
            FROM daily_kline
            WHERE date BETWEEN :s AND :e
              AND {market_where(market_type)}
            ORDER BY code
        """
        params = {'s': start_i, 'e': end_i}
    else:
        sql = f"""
            SELECT DISTINCT code
            FROM minute_kline_period
            WHERE period=:period
              AND date BETWEEN :s AND :e
              AND {market_where(market_type)}
            ORDER BY code
        """
        params = {'period': period, 's': start_i, 'e': end_i}
    codes = [r[0] for r in db.execute(text(sql), params).fetchall()]
    if limit_codes:
        codes = codes[:limit_codes]
    return codes


def load_one_code(db, period: str, code: str, start_i: int, end_i: int) -> pd.DataFrame:
    if period == 'daily':
        sql = """
            SELECT code,date,open,high,low,close,volume
            FROM daily_kline
            WHERE code=:code AND date BETWEEN :s AND :e
            ORDER BY date
        """
        params = {'code': code, 's': start_i, 'e': end_i}
    else:
        sql = """
            SELECT code,date,open,high,low,close,volume
            FROM minute_kline_period
            WHERE code=:code AND period=:period AND date BETWEEN :s AND :e
            ORDER BY date
        """
        params = {'code': code, 'period': period, 's': start_i, 'e': end_i}
    rows = db.execute(text(sql), params).mappings().all()
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()


def make_records(code: str, period: str, ind: pd.DataFrame) -> list[dict]:
    cols = [
        'ma25', 'ma60', 'ma200', 'ma25_slope_3', 'ma60_slope_3',
        'atr14', 'atr20_avg', 'vol_ma5', 'vol_ma60', 'vol_ratio',
        'vol_ma5_cross_vol_ma60', 'price_ma25_deviation_pct',
        'high_20', 'low_20', 'low_30', 'resistance_level',
        'is_abnormal_bar', 'data_quality_status'
    ]
    records = []
    for _, r in ind.iterrows():
        rec = {
            'code': code,
            'period': period,
            'date': int(r['date']),
            'source': 'rebuild',
            'stock_status': 'NORMAL',
            'is_st': 0,
        }
        for c in cols:
            rec[c] = clean_scalar(r.get(c))
        rec['vol_ma5_cross_vol_ma60'] = None if rec['vol_ma5_cross_vol_ma60'] is None else int(rec['vol_ma5_cross_vol_ma60'])
        rec['is_abnormal_bar'] = 0 if rec['is_abnormal_bar'] is None else int(rec['is_abnormal_bar'])
        records.append(rec)
    return records


def rebuild_period(period: str, start: str, end: str, market_type: str, limit_codes: int | None, commit_every: int):
    start_i, end_i = get_period_range(period, start, end)
    print(f"\n=== Rebuild {period} technical_indicator: {start_i} ~ {end_i}, market={market_type} ===")
    total = 0
    with SessionLocal() as db:
        codes = get_codes(db, period, start_i, end_i, market_type, limit_codes)
        print(f"codes={len(codes)}")
        insert_sql = text("""
            INSERT INTO technical_indicator
            (code,period,date,source,stock_status,is_st,
             ma25,ma60,ma200,ma25_slope_3,ma60_slope_3,
             atr14,atr20_avg,vol_ma5,vol_ma60,vol_ratio,vol_ma5_cross_vol_ma60,
             price_ma25_deviation_pct,high_20,low_20,low_30,resistance_level,
             is_abnormal_bar,data_quality_status)
            VALUES
            (:code,:period,:date,:source,:stock_status,:is_st,
             :ma25,:ma60,:ma200,:ma25_slope_3,:ma60_slope_3,
             :atr14,:atr20_avg,:vol_ma5,:vol_ma60,:vol_ratio,:vol_ma5_cross_vol_ma60,
             :price_ma25_deviation_pct,:high_20,:low_20,:low_30,:resistance_level,
             :is_abnormal_bar,:data_quality_status)
        """)
        for idx, code in enumerate(codes, 1):
            df = load_one_code(db, period, code, start_i, end_i)
            if df.empty:
                continue
            ind = compute_indicators(df)
            records = make_records(code, period, ind)
            db.execute(text("""
                DELETE FROM technical_indicator
                WHERE code=:code AND period=:period AND date BETWEEN :s AND :e
            """), {'code': code, 'period': period, 's': start_i, 'e': end_i})
            if records:
                db.execute(insert_sql, records)
                total += len(records)
            if idx % commit_every == 0:
                db.commit()
                print(f"{period}: processed {idx}/{len(codes)}, inserted={total}")
        db.commit()
    print(f"[OK] {period} inserted: {total}")


def main():
    args = parse_args()
    periods = [p.strip() for p in args.periods.split(',') if p.strip()]
    for p in periods:
        if p not in {'daily', '5m', '30m'}:
            raise SystemExit(f"不支持 period={p}，只能 daily/5m/30m")
        rebuild_period(p, args.start, args.end, args.market_type, args.limit_codes, args.commit_every)
    print("\nDONE")


if __name__ == '__main__':
    main()
```

---

### A.25 `scripts/run_2560_analysis.py` — 运行 2560 分析

```python
import argparse
from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.signal_engine_2560 import SignalEngine2560
from app.services.statistics_engine import StatisticsEngine


def market_where(market_type: str) -> str:
    mt = (market_type or "all").lower()

    if mt == "sh":
        return "code LIKE 'sh.%'"
    if mt == "sz":
        return "code LIKE 'sz.%'"
    if mt == "sh60":
        return "code LIKE 'sh.60%'"
    if mt == "sh68":
        return "code LIKE 'sh.68%'"
    if mt == "sz00":
        return "code LIKE 'sz.00%'"
    if mt == "sz30":
        return "code LIKE 'sz.30%'"

    return "(code LIKE 'sh.%' OR code LIKE 'sz.%')"


def load_codes(db, market_type: str, limit: int | None = None):
    """
    优先从 stock_info 取股票池。
    如果 stock_info 没有数据，则从 daily_kline 兜底取。
    """

    where = market_where(market_type)

    sql = f"""
        SELECT DISTINCT code
        FROM stock_info
        WHERE {where}
        ORDER BY code
    """

    if limit:
        sql += " LIMIT :limit"
        rows = db.execute(text(sql), {"limit": limit}).fetchall()
    else:
        rows = db.execute(text(sql)).fetchall()

    codes = [r[0] for r in rows]

    if codes:
        return codes

    # fallback：如果 stock_info 为空，从 daily_kline 取
    sql = f"""
        SELECT DISTINCT code
        FROM daily_kline
        WHERE {where}
        ORDER BY code
    """

    if limit:
        sql += " LIMIT :limit"
        rows = db.execute(text(sql), {"limit": limit}).fetchall()
    else:
        rows = db.execute(text(sql)).fetchall()

    return [r[0] for r in rows]


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--codes", help="逗号分隔，例如 sh.600000,sh.600004")
    parser.add_argument("--source")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--market-type",
        default="all",
        choices=["all", "sh", "sz", "sh60", "sh68", "sz00", "sz30"],
        help="市场范围",
    )
    parser.add_argument(
        "--skip-statistics",
        action="store_true",
        help="跳过 StatisticsEngine 重建统计",
    )

    args = parser.parse_args()

    with SessionLocal() as db:
        if args.codes:
            codes = [x.strip() for x in args.codes.split(",") if x.strip()]
        else:
            codes = load_codes(db, args.market_type, args.limit)

        print(f"market_type={args.market_type}")
        print(f"codes={len(codes)}")

        if not codes:
            print("没有找到可计算股票")
            return

        result = SignalEngine2560(db).run(
            codes=codes,
            source=args.source,
            limit=None,
        )

        print(result)

        if not args.skip_statistics:
            StatisticsEngine(db).rebuild(result["batch_id"])
            print("statistics rebuilt")


if __name__ == "__main__":
    main()
```

---

### A.26 `scripts/fill_recent_with_pytdx_hq.py` — pytdx 实时补数据

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可选：用 pytdx.hq 补最近 K 线。

默认获取 category=0 的 5m 和 category=2 的 30m，写入 minute_kline_period。

示例：
python scripts/fill_recent_with_pytdx_hq.py --codes sh.600000,sz.000001 --count 800
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable
from sqlalchemy import inspect, text

try:
    from pytdx.hq import TdxHq_API
except Exception as exc:
    print("ERROR: 未安装 pytdx。请先执行：pip install pytdx")
    print(f"原始错误: {exc}")
    sys.exit(1)

from app.db.session import SessionLocal


def parse_args():
    p = argparse.ArgumentParser(description='Fill recent 5m/30m by pytdx.hq')
    p.add_argument('--codes', required=True, help='逗号分隔，如 sh.600000,sz.000001')
    p.add_argument('--ip', default='119.147.212.81')
    p.add_argument('--port', type=int, default=7709)
    p.add_argument('--count', type=int, default=800)
    p.add_argument('--periods', default='5m,30m', help='5m,30m')
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def table_columns(db, table_name: str) -> set[str]:
    return {c['name'] for c in inspect(db.bind).get_columns(table_name)}


def parse_code(code: str) -> tuple[int, str, str]:
    c = code.strip().lower()
    if c.startswith('sh.'):
        return 1, c[3:], c
    if c.startswith('sz.'):
        return 0, c[3:], c
    if c.startswith('sh'):
        return 1, c[2:], 'sh.' + c[2:]
    if c.startswith('sz'):
        return 0, c[2:], 'sz.' + c[2:]
    if c.startswith(('6','9')):
        return 1, c, 'sh.' + c
    return 0, c, 'sz.' + c


def insert_rows(db, rows: list[dict], dry_run: bool):
    if not rows: return 0
    cols = table_columns(db, 'minute_kline_period')
    usable = [k for k in rows[0].keys() if k in cols]
    if dry_run: return len(rows)
    sql = text(f"INSERT INTO minute_kline_period ({','.join(usable)}) VALUES ({','.join(':'+c for c in usable)})")
    db.execute(sql, [{k: r.get(k) for k in usable} for r in rows])
    return len(rows)


def main():
    args = parse_args()
    period_map = {'5m': 0, '30m': 2}
    periods = [p.strip() for p in args.periods.split(',') if p.strip()]
    total = 0
    api = TdxHq_API()
    with SessionLocal() as db:
        with api.connect(args.ip, args.port):
            for raw_code in args.codes.split(','):
                market, pure_code, db_code = parse_code(raw_code)
                for period in periods:
                    category = period_map[period]
                    data = api.to_df(api.get_security_bars(category, market, pure_code, 0, args.count))
                    if data is None or data.empty:
                        print(f"empty: {raw_code} {period}")
                        continue
                    rows = []
                    for _, r in data.iterrows():
                        dt = str(r.get('datetime'))
                        rows.append({
                            'code': db_code, 'period': period, 'date': dt,
                            'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']),
                            'volume': float(r.get('vol', r.get('volume', 0)) or 0), 'amount': float(r.get('amount', 0) or 0),
                            'source': 'pytdx_hq',
                        })
                    if not args.dry_run:
                        dates = [x['date'] for x in rows]
                        db.execute(text("DELETE FROM minute_kline_period WHERE code=:code AND period=:period AND date>=:start AND date<=:end"), {'code': db_code, 'period': period, 'start': min(dates), 'end': max(dates)})
                    total += insert_rows(db, rows, args.dry_run)
            if not args.dry_run: db.commit()
    print(json.dumps({'inserted_rows': total, 'dry_run': args.dry_run}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
```

---

### A.27 `scripts/rebuild_statistics.py` — 重建统计

```python
import argparse
from app.db.session import SessionLocal
from app.services.statistics_engine import StatisticsEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild 2560 statistics for a batch")
    parser.add_argument("--batch-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        print(StatisticsEngine(db).rebuild(batch_id=args.batch_id))


if __name__ == "__main__":
    main()
```

---

### A.28 `scripts/backfill_future_returns.py` — 回补未来收益

```python
import argparse
from app.db.session import SessionLocal
from app.services.future_return_engine import FutureReturnEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill future returns for 2560 signals")
    parser.add_argument("--batch-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        print(FutureReturnEngine(db).backfill(batch_id=args.batch_id))


if __name__ == "__main__":
    main()
```

---

### A.29 Shell 脚本汇总

#### `scripts/daily_update_2560.sh` — 每日全量更新

```bash
#!/usr/bin/env bash
set -e

ROOT="/mnt/d/Project/Miller/strategy2560_project_v2_engine"
VIPDOC="/mnt/e/zd_ciccwm/vipdoc"
START="2025-10-01"
TODAY=$(date +%F)

cd $ROOT
source .venv/bin/activate
export PYTHONPATH=$PWD

echo "===== [1/5] daily 导入（并发） ====="

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $START \
  --end $TODAY \
  --daily \
  --markets sh &

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $START \
  --end $TODAY \
  --daily \
  --markets sz &

wait
echo "✅ daily 完成"

echo "===== [2/5] lc5 导入（并发） ====="

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $START \
  --end $TODAY \
  --lc5 \
  --markets sh &

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $START \
  --end $TODAY \
  --lc5 \
  --markets sz &

wait
echo "✅ lc5 完成"

echo "===== [3/5] 5m → 30m（串行，避免锁冲突） ====="

python scripts/build_30m_from_5m.py \
  --start $START \
  --end $TODAY \
  --market-type all

echo "✅ 30m 完成"

echo "===== [4/5] indicator 重算（并发） ====="

python scripts/rebuild_technical_indicator.py \
  --start $START \
  --end $TODAY \
  --market-type sh \
  --periods daily,5m,30m &

python scripts/rebuild_technical_indicator.py \
  --start $START \
  --end $TODAY \
  --market-type sz \
  --periods daily,5m,30m &

wait
echo "✅ indicator 完成"

echo "===== [5/5] 2560 分析（并发） ====="

python scripts/run_2560_analysis.py --market-type sh &
python scripts/run_2560_analysis.py --market-type sz &

wait
echo "✅ 2560 全部完成"

echo "===== ✅ DAILY UPDATE DONE ====="
```

#### `scripts/daily_update_incremental.sh` — 每日增量更新

```bash
#!/usr/bin/env bash
set -e

ROOT="/mnt/d/Project/Miller/strategy2560_project_v2_engine"
VIPDOC="/mnt/e/zd_ciccwm/vipdoc"

TODAY=$(date +%F)

# ===== 窗口参数（经验值，稳定） =====
# 行情补数据窗口
DATA_START=$(date -d '30 days ago' +%F)

# 指标回看窗口（30m 足够 MA200 / VOL_MA60）
INDICATOR_START=$(date -d '90 days ago' +%F)

cd $ROOT
source .venv/bin/activate
export PYTHONPATH=$PWD

echo "===== INCREMENTAL UPDATE START ====="
echo "DATA_START=$DATA_START"
echo "INDICATOR_START=$INDICATOR_START"
echo "TODAY=$TODAY"

# --------------------------------------------------
echo "===== [1/5] daily 导入（最近30天，并发） ====="

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $DATA_START \
  --end $TODAY \
  --daily \
  --markets sh &

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $DATA_START \
  --end $TODAY \
  --daily \
  --markets sz &

wait
echo "✅ daily 完成"

# --------------------------------------------------
echo "===== [2/5] lc5 导入（最近30天，并发） ====="

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $DATA_START \
  --end $TODAY \
  --lc5 \
  --markets sh &

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $DATA_START \
  --end $TODAY \
  --lc5 \
  --markets sz &

wait
echo "✅ lc5 完成"

# --------------------------------------------------
echo "===== [3/5] 5m → 30m（最近30天，串行） ====="

python scripts/build_30m_from_5m.py \
  --start $DATA_START \
  --end $TODAY \
  --market-type all

echo "✅ 30m 完成"

# --------------------------------------------------
echo "===== [4/5] technical_indicator 重算（最近90天，并发） ====="

python scripts/rebuild_technical_indicator.py \
  --start $INDICATOR_START \
  --end $TODAY \
  --market-type sh \
  --periods daily,5m,30m &

python scripts/rebuild_technical_indicator.py \
  --start $INDICATOR_START \
  --end $TODAY \
  --market-type sz \
  --periods daily,5m,30m &

wait
echo "✅ indicator 完成"

# --------------------------------------------------
echo "===== [5/5] 2560 分析（并发） ====="

python scripts/run_2560_analysis.py --market-type sh &
python scripts/run_2560_analysis.py --market-type sz &

wait
echo "✅ 2560 完成"

echo "===== ✅ INCREMENTAL UPDATE DONE ====="
```

#### `scripts/start_webui.sh` — 启动 WebUI

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### `scripts/run_with_path.sh` — 带 PATH 启动

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
.venv/bin/python scripts/run_2560_analysis.py "$@"
```

---

---

## 附录 B — 前端源码

### B.1 `app/static/index.html` — 主页面

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>2560结构分析系统</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">25<br><span>60</span></div>
        <div><h1>2560结构看板</h1><p>结构化分析 / 摸底复盘</p></div>
      </div>
      <nav class="nav">
        <button class="nav-item active" data-view="overview">总览</button>
        <button class="nav-item" data-view="run">入库计算</button>
        <button class="nav-item" data-view="diagnostics">摸底指标</button>
        <button class="nav-item" data-view="signals">信号列表</button>
        <button class="nav-item" data-view="complete">完整结构</button>
        <button class="nav-item" data-view="statistics">结构统计</button>
        <button class="nav-item" data-view="batches">批次管理</button>
        <button class="nav-item" data-view="quality">数据质量</button>
      </nav>
      <div class="risk-note">本系统仅用于结构化行情分析与历史复盘，不构成任何投资建议。</div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div><h2 id="pageTitle">总览</h2><p id="pageSubtitle">查看最新批次、结构完整率、标签分布与系统状态</p></div>
        <div class="actions"><button class="ghost" id="refreshBtn">刷新</button><a class="primary" href="/docs" target="_blank">API文档</a></div>
      </header>
      <section id="systemBanner" class="banner loading">正在检查系统状态...</section>

      <section id="view-overview" class="view active">
        <div class="cards" id="overviewCards"></div>
        <div class="grid two"><div class="panel"><h3>标签分布</h3><div id="tagChart" class="bar-list"></div></div><div class="panel"><h3>最新批次</h3><pre id="latestBatch" class="json-box"></pre></div></div>
      </section>

      <section id="view-run" class="view">
        <div class="panel probe-panel">
          <div class="panel-head split"><h3>全市场摸底计算</h3><span class="probe-note">直接按市场范围全量扫描入库；建议先填 limit 试跑。</span></div>
          <div class="probe-actions">
            <button id="probeShBtn" class="probe-btn">摸底 sh 全部</button>
            <button id="probeSzBtn" class="probe-btn">摸底 sz 全部</button>
            <button id="probeAllBtn" class="probe-btn danger">摸底全部四类</button>
            <input id="probeLimit" type="number" min="1" max="10000" placeholder="可选 limit，如 500；空=全量" />
          </div>
        </div>
        <div class="panel">
          <div class="panel-head split"><h3>选择股票并执行入库计算</h3><button id="runSelectedBtn" class="primary">计算所选股票</button></div>
          <div class="run-grid">
            <div>
              <label class="form-label">搜索 / 筛选股票</label>
              <div class="filters">
                <select id="marketTypeFilter"><option value="all">全部四类</option><option value="sz00">sz 00 深市</option><option value="sz30">sz 30 创业板</option><option value="sh60">sh 60 沪市</option><option value="sh68">sh 68 科创板</option><option value="sz">sz 全部</option><option value="sh">sh 全部</option></select>
                <input id="stockSearch" placeholder="代码/名称，如 sh.600000、688416" />
                <button id="searchStockBtn">搜索</button>
                <button id="selectCurrentBtn" class="soft">全选当前结果</button>
                <button id="selectByFilterBtn" class="soft">按筛选全选200只</button>
                <button id="clearSelectedBtn" class="ghost">清空选择</button>
                <span id="selectedCountHint" class="selected-count-hint">已选 0</span>
              </div>
              <div class="table-wrap stock-picker"><table id="stockTable"></table></div>
            </div>
            <div>
              <label class="form-label">已选股票代码</label>
              <textarea id="selectedCodes" placeholder="可手动输入，逗号分隔，如 sh.600000,sz.301419"></textarea>
              <label class="form-label">数据源，可选</label><input id="runSource" placeholder="为空表示不限制 source" />
              <label class="form-label">未选择股票时按 limit 自动取 stock_info</label><input id="runLimit" type="number" min="1" max="10000" placeholder="例如 500；为空表示全量" />
              <label class="check-line"><input id="rebuildStats" type="checkbox" checked /> 计算完成后重建统计</label>
              <pre id="runResult" class="json-box run-result">等待执行...</pre>
            </div>
          </div>
        </div>
      </section>

      <section id="view-diagnostics" class="view">
        <div class="panel">
          <div class="panel-head split"><h3>2560 摸底指标明细</h3><button id="diagLoadBtn" class="primary">加载指标</button></div>
          <div class="diag-controls">
            <select id="diagMarket"><option value="all">全部四类</option><option value="sh">sh 全部</option><option value="sz">sz 全部</option><option value="sh60">sh 60 沪市</option><option value="sh68">sh 68 科创板</option><option value="sz00">sz 00 深市</option><option value="sz30">sz 30 创业板</option></select>
            <input id="diagLimit" type="number" min="1" max="5000" value="500" />
            <input id="diagQ" placeholder="代码/名称过滤，可空" />
            <label class="check-line"><input id="diagNearOnly" type="checkbox" /> 只看接近满足条件</label>
          </div>
          <div id="diagSummaryCards" class="cards diag-cards"></div>
          <div class="grid two"><div class="panel inner"><h3>未命中原因柱状图</h3><div id="diagBar" class="diag-bar"></div></div><div class="panel inner"><h3>未命中原因饼图</h3><div id="diagPie" class="diag-pie"></div><div id="diagLegend" class="diag-legend"></div></div></div>
          <div class="panel inner"><h3>指标明细表</h3><div id="diagTable"></div></div>
        </div>
      </section>

      <section id="view-signals" class="view"><div class="panel"><div class="panel-head split"><h3>信号列表</h3><div class="filters"><input id="filterCode" placeholder="代码，如 sh.600000" /><select id="filterStatus"><option value="">全部结构状态</option><option value="结构完整">结构完整</option><option value="部分满足">部分满足</option><option value="明显缺失">明显缺失</option><option value="数据不足">数据不足</option></select><input id="filterTag" placeholder="标签，如 #缺量" /><button id="applySignalFilter">筛选</button></div></div><div class="table-wrap"><table id="signalsTable"></table></div><div class="pager"><button id="prevPage">上一页</button><span id="pageInfo">第 1 页</span><button id="nextPage">下一页</button></div></div></section>
      <section id="view-complete" class="view"><div class="panel"><h3>最近20条完整结构案例</h3><div class="table-wrap"><table id="completeTable"></table></div></div></section>
      <section id="view-statistics" class="view"><div class="panel"><div class="panel-head split"><h3>结构统计</h3><select id="statType"><option value="">全部统计</option><option value="BY_STRUCTURE_STATUS">按结构状态</option><option value="BY_TAG">按标签</option><option value="BY_INDUSTRY">按行业</option><option value="BY_BOARD">按板块</option><option value="BY_CONCEPT">按概念</option><option value="BY_DATA_QUALITY">按数据质量</option></select></div><div class="table-wrap"><table id="statsTable"></table></div></div></section>
      <section id="view-batches" class="view"><div class="panel"><h3>分析批次</h3><div class="table-wrap"><table id="batchesTable"></table></div></div></section>
      <section id="view-quality" class="view"><div class="panel"><h3>数据质量</h3><div class="table-wrap"><table id="qualityTable"></table></div></div></section>
      <section id="detailDrawer" class="drawer hidden"><div class="drawer-card"><div class="drawer-head"><h3>信号详情</h3><button id="closeDrawer" class="ghost">关闭</button></div><pre id="detailContent" class="json-box"></pre></div></section>
    </main>
  </div>
  <script src="/static/app.js"></script>
</body>
</html>
```

---

### B.2 `app/static/app.js` — 前端核心逻辑 (含菜单 wiring)

```javascript
const state={page:1,pageSize:50,view:'overview',selected:new Set(),marketType:'all',currentStocks:[]};
const $=id=>document.getElementById(id);

async function api(url,opts){
  const r=await fetch(url,opts);
  const d=await r.json();
  if(!r.ok||d.success===false) throw new Error(d.message||r.statusText);
  return d.data??d
}

function fmt(v){return v===null||v===undefined?'-':v}
function num(v){return v===null||v===undefined?'-':Number(v).toFixed(3)}
function pct(v){return v===null||v===undefined?'-':`${Number(v).toFixed(2)}%`}
function bool(v){return v===true?'是':v===false?'否':'-'}

function badgeStatus(s){
  const cls=s==='结构完整'?'ok':s==='部分满足'?'mid':s==='明显缺失'?'bad':'gray';
  return `<span class="badge ${cls}">${fmt(s)}</span>`
}

function renderTable(el,cols,rows,onClick,rowClass){
  if(!rows||!rows.length){el.innerHTML='<tbody><tr><td>暂无数据</td></tr></tbody>';return}
  el.innerHTML=`<thead><tr>${cols.map(c=>`<th>${c.label}</th>`).join('')}</tr></thead><tbody>`+
    rows.map(r=>`<tr class="${rowClass?rowClass(r):''}" data-id="${r.id||r.code||''}">${cols.map(c=>`<td>${c.render?c.render(r):fmt(r[c.key])}</td>`).join('')}</tr>`).join('')+
    '</tbody>';
  if(onClick) el.querySelectorAll('tbody tr').forEach(tr=>tr.addEventListener('click',()=>onClick(tr.dataset.id,tr)))
}

function syncSelectedBox(){if($('selectedCodes')) $('selectedCodes').value=[...state.selected].join(',')}
function updateSelectedHint(){if($('selectedCountHint')) $('selectedCountHint').textContent=`已选 ${state.selected.size}`}

async function loadHealth(){
  try{
    const h=await api('/health');
    $('systemBanner').className='banner';
    $('systemBanner').textContent=`系统状态：${h.status||'ok'} / 数据库：${h.database?'已连接':'未连接'}`
  }catch(e){
    $('systemBanner').className='banner warn';
    $('systemBanner').textContent=`系统状态异常：${e.message}`
  }
}

async function loadOverview(){
  const d=await api('/api/strategy/2560/overview');
  const s=d.summary||{};
  const total=Number(s.total_signals||0),complete=Number(s.complete_count||0);
  const rate=total?(complete/total*100).toFixed(1)+'%':'-';
  $('overviewCards').innerHTML=[
    ['总信号数',total],['结构完整',complete],['部分满足',s.partial_count||0],
    ['明显缺失',s.missing_count||0],['完整率',rate]
  ].map(([l,v])=>`<div class="card"><div class="label">${l}</div><div class="value">${v}</div></div>`).join('');
  $('latestBatch').textContent=JSON.stringify(d.latest_batch||{},null,2);
  const tags=d.tag_distribution||[],max=Math.max(...tags.map(t=>Number(t.count||0)),1);
  $('tagChart').innerHTML=tags.length?
    tags.map(t=>`<div class="bar-row"><div>${t.tag_name}</div><div class="bar-bg"><div class="bar-fill" style="width:${Number(t.count||0)/max*100}%"></div></div><div>${t.count}</div></div>`).join('')
    :'暂无标签数据'
}

async function loadStocks(){
  const q=$('stockSearch').value.trim();
  const mt=$('marketTypeFilter').value;
  state.marketType=mt;
  const d=await api('/api/strategy/2560/stocks?limit=200&market_type='+encodeURIComponent(mt)+(q?'&q='+encodeURIComponent(q):''));
  state.currentStocks=d||[];
  updateSelectedHint();
  renderTable($('stockTable'),[
    {label:'选择',render:r=>state.selected.has(r.code)?'✓':''},
    {label:'类型',render:r=>r.board_type||r.market_type||'-'},
    {label:'市场代码',render:r=>r.market_code||r.code},
    {label:'代码',key:'code'},
    {label:'名称',key:'name'},
    {label:'行业',key:'industry_name'}
  ],d||[],code=>{
    if(state.selected.has(code)) state.selected.delete(code);
    else state.selected.add(code);
    syncSelectedBox(); updateSelectedHint(); loadStocks()
  },r=>state.selected.has(r.code)?'stock-row selected':'stock-row')
}

function selectCurrentStocks(){
  (state.currentStocks||[]).forEach(r=>{if(r.code) state.selected.add(r.code)});
  syncSelectedBox(); updateSelectedHint(); loadStocks()
}

async function selectByFilterLimit(){
  const mt=$('marketTypeFilter').value;
  const q=$('stockSearch').value.trim();
  const d=await api('/api/strategy/2560/stocks?limit=200&market_type='+encodeURIComponent(mt)+(q?'&q='+encodeURIComponent(q):''));
  (d||[]).forEach(r=>{if(r.code) state.selected.add(r.code)});
  syncSelectedBox(); updateSelectedHint(); loadStocks()
}

async function runSelected(){
  const manual=$('selectedCodes').value.split(/[，,\s]+/).map(x=>x.trim()).filter(Boolean);
  manual.forEach(c=>state.selected.add(c));
  syncSelectedBox();
  const codes=[...state.selected];
  const limitVal=$('runLimit').value.trim();
  const mt=$('marketTypeFilter').value;
  const payload={codes,source:$('runSource').value.trim()||null,limit:codes.length?null:(limitVal?Number(limitVal):null),rebuild_statistics:$('rebuildStats').checked,market_type:mt};
  $('runResult').textContent='正在计算并入库，请稍候...';
  try{
    const d=await api('/api/strategy/2560/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    $('runResult').textContent=JSON.stringify(d,null,2);
    await loadOverview(); await loadBatches()
  }catch(e){$('runResult').textContent='运行失败：'+e.message}
}

async function runProbe(mt){
  const limitText=$('probeLimit').value.trim();
  const limit=limitText?Number(limitText):null;
  const label=mt==='sh'?'sh 全部':mt==='sz'?'sz 全部':'全部四类';
  if(!confirm(`确认开始摸底计算：${label}${limit?'，limit='+limit:'，全量'}？`)) return;
  $('runResult').textContent=`正在摸底计算 ${label}...`;
  const payload={codes:[],source:$('runSource').value.trim()||null,limit,rebuild_statistics:$('rebuildStats').checked,market_type:mt};
  try{
    const d=await api('/api/strategy/2560/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    $('runResult').textContent=JSON.stringify(d,null,2);
    await loadOverview(); await loadBatches()
  }catch(e){$('runResult').textContent='摸底计算失败：'+e.message}
}

function color(i){return ['#2563eb','#dc2626','#d97706','#16a34a','#7c3aed','#0891b2','#be123c','#4b5563'][i%8]}

async function loadDiagnostics(){
  const mt=$('diagMarket').value,limit=$('diagLimit').value||500,q=$('diagQ').value.trim(),near=$('diagNearOnly').checked?1:0;
  $('diagTable').innerHTML='正在加载...';
  try{
    const d=await api('/api/strategy/2560/probe-indicators?market_type='+encodeURIComponent(mt)+'&limit='+encodeURIComponent(limit)+'&near_only='+near+(q?'&q='+encodeURIComponent(q):''));
    renderDiagSummary(d.summary||{});
    renderDiagCharts(d.reason_stats||[]);
    renderDiagTable(d.items||[])
  }catch(e){$('diagTable').innerHTML='加载失败：'+e.message}
}

function renderDiagSummary(s){
  $('diagSummaryCards').innerHTML=[
    ['加载数量',s.total||0],['原始数量',s.raw_total||0],['缺30m',s.missing_30m||0],
    ['缺日线',s.missing_daily||0],['接近满足',s.near_count||0]
  ].map(([l,v])=>`<div class="card"><div class="label">${l}</div><div class="value">${v}</div></div>`).join('')
}

function renderDiagCharts(stats){
  const max=Math.max(...stats.map(x=>x.count||0),1);
  $('diagBar').innerHTML=stats.slice(0,12).map((x,i)=>
    `<div class="diag-bar-row"><span>${x.reason}</span><div class="diag-bar-bg"><div style="width:${(x.count/max*100).toFixed(1)}%;background:${color(i)}"></div></div><b>${x.count}</b></div>`
  ).join('')||'暂无';
  const total=stats.reduce((a,b)=>a+(b.count||0),0);
  let acc=0,gs=[];
  stats.slice(0,8).forEach((x,i)=>{
    const start=acc/total*360; acc+=x.count||0; const end=acc/total*360;
    gs.push(`${color(i)} ${start}deg ${end}deg`)
  });
  $('diagPie').style.background=total?`conic-gradient(${gs.join(',')})`:'#e5e7eb';
  $('diagLegend').innerHTML=stats.slice(0,8).map((x,i)=>
    `<div><i style="background:${color(i)}"></i>${x.reason} (${x.count})</div>`
  ).join('')
}

function renderDiagTable(items){
  if(!items.length){$('diagTable').innerHTML='<div class="diag-empty">暂无数据</div>';return}
  const cols=['代码','名称','类型','日线','30m','5m','最新30m','收盘','MA25','斜率','偏离%','量比','贴MA25','斜率OK','量能OK','状态','未命中原因'];
  $('diagTable').innerHTML='<div class="table-wrap"><table><thead><tr>'+cols.map(x=>`<th>${x}</th>`).join('')+'</tr></thead><tbody>'+
    items.map(r=>`<tr class="${r.near_match?'diag-near':''}"><td>${r.code||'-'}</td><td>${r.name||'-'}</td><td>${r.board_type||'-'}</td><td>${r.daily_count}</td><td>${r.k30_count}</td><td>${r.k5_count}</td><td>${r.latest_30m_time||'-'}</td><td>${num(r.close_30m)}</td><td>${num(r.ma25_30m)}</td><td>${num(r.ma25_slope_3)}</td><td>${num(r.price_ma25_deviation_pct)}</td><td>${num(r.vol_ratio)}</td><td>${bool(r.price_near_ma25)}</td><td>${bool(r.ma25_slope_ok)}</td><td>${bool(r.volume_structure_ok)}</td><td>${r.status}</td><td>${r.reasons}</td></tr>`).join('')+
    '</tbody></table></div>'
}

async function loadSignals(){
  const p=new URLSearchParams({page:state.page,page_size:state.pageSize});
  if($('filterCode').value) p.set('code',$('filterCode').value.trim());
  if($('filterStatus').value) p.set('structure_status',$('filterStatus').value);
  if($('filterTag').value) p.set('tag',$('filterTag').value.trim());
  const d=await api('/api/strategy/2560/signals?'+p.toString());
  $('pageInfo').textContent=`第 ${d.page} 页 / 共 ${d.total} 条`;
  renderTable($('signalsTable'),[
    {label:'时间',key:'signal_time'},{label:'代码',key:'code'},{label:'名称',key:'name'},
    {label:'价格',key:'price'},{label:'行业',key:'industry_name'},
    {label:'结构状态',render:r=>badgeStatus(r.structure_status)},
    {label:'标签',key:'missing_tags'},{label:'数据质量',key:'data_quality_status'},
    {label:'说明',key:'explain_text'}
  ],d.items||[],id=>id&&showDetail(id))
}

async function showDetail(id){
  const d=await api('/api/strategy/2560/signals/'+id);
  $('detailContent').textContent=JSON.stringify(d,null,2);
  $('detailDrawer').classList.remove('hidden')
}

async function loadComplete(){
  const d=await api('/api/strategy/2560/complete-cases?limit=20');
  renderTable($('completeTable'),[
    {label:'时间',key:'signal_time'},{label:'代码',key:'code'},{label:'名称',key:'name'},
    {label:'价格',key:'price'},{label:'1日',render:r=>pct(r.future_return_1d)},
    {label:'3日',render:r=>pct(r.future_return_3d)},{label:'5日',render:r=>pct(r.future_return_5d)}
  ],d||[])
}

async function loadStatistics(){
  const type=$('statType').value;
  const d=await api(type?'/api/strategy/2560/statistics?stat_type='+encodeURIComponent(type):'/api/strategy/2560/statistics');
  renderTable($('statsTable'),[
    {label:'批次',key:'batch_id'},{label:'日期',key:'stat_date'},{label:'类型',key:'stat_type'},
    {label:'分组',key:'group_key'},{label:'样本',key:'sample_count'},
    {label:'5日均值',render:r=>pct(r.avg_return_5d)}
  ],d||[])
}

async function loadBatches(){
  const d=await api('/api/strategy/2560/batches');
  renderTable($('batchesTable'),[
    {label:'批次ID',key:'batch_id'},{label:'策略',key:'strategy_code'},
    {label:'版本',key:'strategy_version'},{label:'运行时间',key:'run_time'},
    {label:'状态',key:'status'},{label:'说明',key:'message'}
  ],d||[])
}

async function loadQuality(){
  const d=await api('/api/data-quality/summary');
  renderTable($('qualityTable'),[
    {label:'日期',key:'check_date'},{label:'周期',key:'period'},{label:'数据源',key:'source'},
    {label:'应有标的',key:'total_symbols'},{label:'可用标的',key:'available_symbols'},
    {label:'缺失',key:'missing_symbols'},{label:'异常K线',key:'abnormal_bar_count'},
    {label:'状态',key:'status'}
  ],d||[])
}

async function refresh(){
  await loadHealth();
  if(state.view==='overview') await loadOverview();
  if(state.view==='run') await loadStocks();
  if(state.view==='diagnostics') await loadDiagnostics();
  if(state.view==='signals') await loadSignals();
  if(state.view==='complete') await loadComplete();
  if(state.view==='statistics') await loadStatistics();
  if(state.view==='batches') await loadBatches();
  if(state.view==='quality') await loadQuality()
}

const titles={
  overview:['总览','查看最新批次、结构完整率、标签分布与系统状态'],
  run:['入库计算','支持选择股票、全选、sh/sz 全部摸底计算'],
  diagnostics:['摸底指标','查看2560各项指标、未命中原因统计，以及接近满足条件的股票'],
  signals:['信号列表','逐条查看2560结构条件、标签与解释'],
  complete:['完整结构','查看最近结构完整案例及后续表现'],
  statistics:['结构统计','按结构状态、标签、行业、板块、概念统计'],
  batches:['批次管理','查看分析批次、版本、运行状态'],
  quality:['数据质量','查看日线/分钟线完整性与异常情况']
};

// ===== 侧边栏菜单 wiring 逻辑 =====
// 遍历所有 .nav-item 按钮，点击时：
// 1. 清除所有按钮的 active 类
// 2. 给当前按钮加 active 类
// 3. 隐藏所有 .view 区域
// 4. 显示 data-view 对应的区域
// 5. 更新页面标题和副标题
// 6. 刷新数据
document.querySelectorAll('.nav-item').forEach(b=>b.addEventListener('click',async()=>{
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  state.view=b.dataset.view;
  state.page=1;
  $('view-'+state.view).classList.add('active');
  $('pageTitle').textContent=titles[state.view][0];
  $('pageSubtitle').textContent=titles[state.view][1];
  await refresh()
}));

// ===== 全局事件绑定 =====
$('refreshBtn').onclick=refresh;
$('searchStockBtn').onclick=loadStocks;
$('selectCurrentBtn').onclick=selectCurrentStocks;
$('selectByFilterBtn').onclick=selectByFilterLimit;
$('runSelectedBtn').onclick=runSelected;
$('clearSelectedBtn').onclick=()=>{
  state.selected.clear();
  syncSelectedBox();
  updateSelectedHint();
  loadStocks();
  $('runResult').textContent='等待执行...'
};
$('probeShBtn').onclick=()=>runProbe('sh');
$('probeSzBtn').onclick=()=>runProbe('sz');
$('probeAllBtn').onclick=()=>runProbe('all');
$('diagLoadBtn').onclick=loadDiagnostics;
$('applySignalFilter').onclick=()=>{state.page=1;loadSignals()};
$('prevPage').onclick=()=>{if(state.page>1){state.page--;loadSignals()}};
$('nextPage').onclick=()=>{state.page++;loadSignals()};
$('statType').onchange=loadStatistics;
$('closeDrawer').onclick=()=>$('detailDrawer').classList.add('hidden');

// 页面加载时首次刷新
refresh();
```

---

### B.3 `app/static/styles.css` — 主样式

```css
:root{--bg:#f5f7fb;--panel:#fff;--text:#111827;--muted:#6b7280;--line:#e5e7eb;--blue:#2563eb;--blue2:#1d4ed8;--shadow:0 12px 30px rgba(15,23,42,.08);--radius:16px}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",Arial,sans-serif}
.app-shell{display:flex;min-height:100vh}
.sidebar{width:280px;background:#0f172a;color:#e5e7eb;padding:22px;display:flex;flex-direction:column;gap:24px;position:sticky;top:0;height:100vh}
.brand{display:flex;gap:14px;align-items:center}
.brand-mark{width:54px;height:54px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#22c55e);display:grid;place-items:center;font-weight:800;line-height:16px;color:#fff}
.brand-mark span{font-size:13px}
.brand h1{font-size:18px;margin:0}
.brand p{margin:4px 0 0;color:#94a3b8;font-size:12px}
.nav{display:flex;flex-direction:column;gap:8px}
.nav-item{border:0;background:transparent;color:#cbd5e1;text-align:left;padding:12px 14px;border-radius:12px;cursor:pointer;font-size:15px}
.nav-item:hover,.nav-item.active{background:#1e293b;color:#fff}
.risk-note{margin-top:auto;color:#cbd5e1;background:#1e293b;border:1px solid #334155;border-radius:14px;padding:14px;font-size:12px;line-height:1.7}
.main{flex:1;padding:26px;min-width:0}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.topbar h2{margin:0;font-size:28px}
.topbar p{margin:6px 0 0;color:var(--muted)}
.actions{display:flex;gap:10px}
button,.primary,.ghost,.soft{border:0;border-radius:10px;padding:10px 14px;cursor:pointer;text-decoration:none;font-weight:600}
.primary{background:var(--blue);color:#fff}
.primary:hover{background:var(--blue2)}
.ghost{background:#fff;color:#111827;border:1px solid var(--line)}
.soft{background:#eef2ff;color:#1d4ed8}
.banner{padding:12px 16px;border-radius:14px;margin-bottom:18px;background:#ecfdf5;border:1px solid #bbf7d0;color:#166534}
.banner.loading{background:#eff6ff;border-color:#bfdbfe;color:#1d4ed8}
.banner.warn{background:#fff7ed;border-color:#fed7aa;color:#9a3412}
.view{display:none}
.view.active{display:block}
.cards{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:14px;margin-bottom:16px}
.card,.panel{background:var(--panel);border-radius:var(--radius);box-shadow:var(--shadow);border:1px solid rgba(226,232,240,.8)}
.card{padding:18px}
.card .label{color:var(--muted);font-size:13px}
.card .value{font-size:30px;font-weight:800;margin-top:6px}
.grid.two{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}
.panel{padding:18px;margin-bottom:16px}
.panel.inner{box-shadow:none}
.panel h3{margin-top:0}
.panel-head{display:flex;align-items:center;margin-bottom:12px}
.panel-head h3{margin:0;font-size:18px}
.panel-head.split{justify-content:space-between;gap:16px}
.filters,.probe-actions,.diag-controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input,select,textarea{border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff;min-width:140px;font-family:inherit}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:#fff}
table{width:100%;border-collapse:collapse;background:#fff}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);font-size:13px;white-space:nowrap;text-align:left}
th{background:#f8fafc;color:#475569;font-weight:700}
tr:hover td{background:#f8fafc}
.badge{display:inline-block;border-radius:999px;padding:4px 8px;font-size:12px;font-weight:700}
.badge.ok{background:#dcfce7;color:#166534}
.badge.mid{background:#fef3c7;color:#92400e}
.badge.bad{background:#fee2e2;color:#991b1b}
.badge.gray{background:#e5e7eb;color:#374151}
.json-box{background:#0f172a;color:#dbeafe;border-radius:12px;padding:14px;overflow:auto;max-height:520px}
.bar-list{display:flex;flex-direction:column;gap:10px}
.bar-row{display:grid;grid-template-columns:120px 1fr 60px;gap:10px;align-items:center}
.bar-bg{height:12px;background:#e5e7eb;border-radius:999px;overflow:hidden}
.bar-fill{height:100%;background:linear-gradient(90deg,#2563eb,#22c55e)}
.pager{display:flex;gap:12px;align-items:center;justify-content:flex-end;margin-top:12px}
.drawer{position:fixed;inset:0;background:rgba(15,23,42,.45);display:grid;place-items:center;padding:30px;z-index:20}
.drawer.hidden{display:none}
.drawer-card{background:#fff;width:min(900px,96vw);max-height:88vh;overflow:auto;border-radius:18px;padding:18px;box-shadow:var(--shadow)}
.drawer-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.run-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:16px}
.form-label{display:block;font-weight:700;margin:12px 0 8px;color:#374151}
.stock-picker{max-height:460px}
.stock-row{cursor:pointer}
.stock-row.selected td{background:#dbeafe!important}
textarea#selectedCodes{width:100%;min-height:130px}
.check-line{display:flex;gap:8px;align-items:center;margin:12px 0}
.run-result{min-height:180px}
.selected-count-hint{display:inline-flex;align-items:center;padding:0 10px;color:#475569;font-size:13px;font-weight:700}
.probe-panel{border:1px solid #bfdbfe;background:#eff6ff}
.probe-btn{background:#2563eb;color:#fff}
.probe-btn.danger{background:#0f172a}
.probe-note{color:#475569;font-size:13px}
.diag-cards{grid-template-columns:repeat(5,minmax(120px,1fr))}
.diag-bar{display:flex;flex-direction:column;gap:9px}
.diag-bar-row{display:grid;grid-template-columns:150px 1fr 52px;gap:10px;align-items:center;font-size:13px}
.diag-bar-bg{height:12px;border-radius:999px;background:#e5e7eb;overflow:hidden}
.diag-bar-bg div{height:100%}
.diag-pie{width:190px;height:190px;border-radius:50%;background:#e5e7eb;margin:auto}
.diag-legend{display:grid;gap:6px;margin-top:12px;font-size:13px}
.diag-legend div{display:flex;gap:8px;align-items:center}
.diag-legend i{display:inline-block;width:12px;height:12px;border-radius:3px}
.diag-near td{background:#ecfdf5!important}
.diag-empty{padding:14px;color:#64748b}
@media(max-width:1100px){
  .sidebar{width:230px}
  .cards,.diag-cards{grid-template-columns:repeat(2,1fr)}
  .grid.two,.run-grid{grid-template-columns:1fr}
}
@media(max-width:760px){
  .app-shell{display:block}
  .sidebar{position:static;width:auto;height:auto}
  .main{padding:16px}
  .topbar{display:block}
  .actions{margin-top:12px}
  .cards{grid-template-columns:1fr}
  .filters{display:grid;width:100%}
  input,select,textarea{width:100%}
}
```

---

### B.4 `app/static/diagnostic_menu_append.js` — 摸底指标菜单动态注入

```javascript
(function(){
  if(window.__strategy2560DiagnosticMenuInstalled) return;
  window.__strategy2560DiagnosticMenuInstalled=true;

  function $(id){return document.getElementById(id)}

  async function api(url,opts){
    const r=await fetch(url,opts);
    const d=await r.json();
    if(!r.ok||d.success===false) throw new Error(d.message||r.statusText);
    return d.data??d
  }

  function num(v){return v===null||v===undefined?'-':Number(v).toFixed(3)}
  function bool(v){return v===true?'是':v===false?'否':'-'}
  function colors(i){return ['#2563eb','#dc2626','#d97706','#16a34a','#7c3aed','#0891b2','#be123c','#4b5563'][i%8]}

  // --- 确保导航栏有 "摸底指标" 按钮 ---
  function ensureDiagView(){
    // 如果 nav 中还没有摸底指标按钮，插入到第 3 个位置
    if(!$('diagNavBtn')){
      const nav=document.querySelector('.nav');
      if(nav){
        const b=document.createElement('button');
        b.id='diagNavBtn';
        b.className='nav-item';
        b.textContent='摸底指标';
        b.dataset.view='diagnostics';
        nav.insertBefore(b,nav.children[2]||null);
        b.onclick=showDiagView
      }
    }

    // 如果还没有 view-diagnostics 区域，创建它
    if(!$('view-diagnostics')){
      const main=document.querySelector('.main');
      const sec=document.createElement('section');
      sec.id='view-diagnostics';
      sec.className='view';
      sec.innerHTML=`
        <div class="panel">
          <div class="panel-head split">
            <h3>2560 摸底指标明细</h3>
            <button id="diagLoadBtn" class="primary">加载指标</button>
          </div>
          <div class="diag-controls">
            <select id="diagMarket">
              <option value="all">全部四类</option>
              <option value="sh">sh 全部</option>
              <option value="sz">sz 全部</option>
              <option value="sh60">sh 60 沪市</option>
              <option value="sh68">sh 68 科创板</option>
              <option value="sz00">sz 00 深市</option>
              <option value="sz30">sz 30 创业板</option>
            </select>
            <input id="diagLimit" type="number" min="1" max="5000" value="500"/>
            <input id="diagQ" placeholder="代码/名称过滤，可空"/>
            <label class="check-line">
              <input id="diagNearOnly" type="checkbox"/> 只看接近满足条件
            </label>
          </div>
          <div id="diagSummaryCards" class="cards diag-cards"></div>
          <div class="grid two">
            <div class="panel">
              <h3>未命中原因柱状图</h3>
              <div id="diagBar" class="diag-bar"></div>
            </div>
            <div class="panel">
              <h3>未命中原因饼图</h3>
              <div id="diagPieWrap">
                <div id="diagPie" class="diag-pie"></div>
                <div id="diagLegend" class="diag-legend"></div>
              </div>
            </div>
          </div>
          <div class="panel">
            <h3>指标明细表</h3>
            <div id="diagTable"></div>
          </div>
        </div>
      `;
      main.appendChild(sec);
      $('diagLoadBtn').onclick=loadDiagnostics
    }
  }

  function showDiagView(){
    ensureDiagView();
    document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
    $('diagNavBtn').classList.add('active');
    document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
    $('view-diagnostics').classList.add('active');
    if($('pageTitle')) $('pageTitle').textContent='摸底指标';
    if($('pageSubtitle')) $('pageSubtitle').textContent='查看2560各项指标、未命中原因统计，以及接近满足条件的股票';
  }

  async function loadDiagnostics(){
    const mt=$('diagMarket').value,
          limit=$('diagLimit').value||500,
          q=$('diagQ').value.trim(),
          near=$('diagNearOnly').checked?1:0;
    $('diagTable').innerHTML='正在加载...';
    const d=await api('/api/strategy/2560/probe-indicators?market_type='+encodeURIComponent(mt)+'&limit='+encodeURIComponent(limit)+'&near_only='+near+(q?'&q='+encodeURIComponent(q):''));
    renderSummary(d.summary||{});
    renderCharts(d.reason_stats||[]);
    renderTable(d.items||[])
  }

  function renderSummary(s){
    $('diagSummaryCards').innerHTML=[
      ['加载数量',s.total||0],['原始数量',s.raw_total||0],
      ['缺30m',s.missing_30m||0],['缺日线',s.missing_daily||0],
      ['接近满足',s.near_count||0]
    ].map(([l,v])=>`<div class="card"><div class="label">${l}</div><div class="value">${v}</div></div>`).join('')
  }

  function renderCharts(stats){
    const max=Math.max(...stats.map(x=>x.count||0),1);
    $('diagBar').innerHTML=stats.slice(0,12).map((x,i)=>
      `<div class="diag-bar-row"><span>${x.reason}</span><div class="diag-bar-bg"><div style="width:${(x.count/max*100).toFixed(1)}%;background:${colors(i)}"></div></div><b>${x.count}</b></div>`
    ).join('')||'暂无';
    const total=stats.reduce((a,b)=>a+(b.count||0),0);
    let acc=0,gradients=[];
    stats.slice(0,8).forEach((x,i)=>{
      const start=acc/total*360;
      acc+=x.count||0;
      const end=acc/total*360;
      gradients.push(`${colors(i)} ${start}deg ${end}deg`)
    });
    $('diagPie').style.background=total?`conic-gradient(${gradients.join(',')})`:'#e5e7eb';
    $('diagLegend').innerHTML=stats.slice(0,8).map((x,i)=>
      `<div><i style="background:${colors(i)}"></i>${x.reason} (${x.count})</div>`
    ).join('')
  }

  function renderTable(items){
    if(!items.length){$('diagTable').innerHTML='<div class="diag-empty">暂无数据</div>';return}
    const cols=['代码','名称','类型','日线','30m','5m','最新30m','收盘','MA25','斜率','偏离%','量比','贴MA25','斜率OK','量能OK','状态','未命中原因'];
    $('diagTable').innerHTML='<div class="table-wrap"><table><thead><tr>'+
      cols.map(x=>`<th>${x}</th>`).join('')+'</tr></thead><tbody>'+
      items.map(r=>`<tr class="${r.near_match?'diag-near':''}">
        <td>${r.code||'-'}</td><td>${r.name||'-'}</td><td>${r.board_type||'-'}</td>
        <td>${r.daily_count}</td><td>${r.k30_count}</td><td>${r.k5_count}</td>
        <td>${r.latest_30m_time||'-'}</td><td>${num(r.close_30m)}</td>
        <td>${num(r.ma25_30m)}</td><td>${num(r.ma25_slope_3)}</td>
        <td>${num(r.price_ma25_deviation_pct)}</td><td>${num(r.vol_ratio)}</td>
        <td>${bool(r.price_near_ma25)}</td><td>${bool(r.ma25_slope_ok)}</td>
        <td>${bool(r.volume_structure_ok)}</td><td>${r.status}</td><td>${r.reasons}</td>
      </tr>`).join('')+'</tbody></table></div>'
  }

  // 延迟初始化 + 全局 click 监听 (兼容 HTML 未包含该区域的老版本)
  setTimeout(ensureDiagView,300);
  document.addEventListener('click',()=>setTimeout(ensureDiagView,50));
})();
```

---

### B.5 `app/static/diagnostic_append.js` — 入库计算页增量诊断面板

```javascript
// Minimal additive diagnostic helper. 保留已有 UI 行为，在 run 页面注入诊断面板。
(function(){
  function $(id){return document.getElementById(id)}

  async function api(url,opts){
    const r=await fetch(url,opts);
    const d=await r.json();
    if(!r.ok||d.success===false) throw new Error(d.message||r.statusText);
    return d.data??d
  }

  function renderDiagTable(items){
    const box=$('diagTable');
    if(!box) return;
    if(!items||!items.length){box.innerHTML='<div class="diag-empty">暂无摸底指标数据</div>';return}
    const cols=['代码','名称','类型','日线','30m','5m','最新30m','MA25','斜率','偏离%','量比','贴MA25','斜率OK','量能OK','状态','未命中原因'];
    box.innerHTML='<div class="table-wrap"><table><thead><tr>'+
      cols.map(x=>`<th>${x}</th>`).join('')+'</tr></thead><tbody>'+
      items.map(r=>`<tr>
        <td>${r.code||'-'}</td><td>${r.name||'-'}</td><td>${r.board_type||'-'}</td>
        <td>${r.daily_count}</td><td>${r.k30_count}</td><td>${r.k5_count}</td>
        <td>${r.latest_30m_time||'-'}</td><td>${num(r.ma25_30m)}</td>
        <td>${num(r.ma25_slope_3)}</td><td>${num(r.price_ma25_deviation_pct)}</td>
        <td>${num(r.vol_ratio)}</td><td>${bool(r.price_near_ma25)}</td>
        <td>${bool(r.ma25_slope_ok)}</td><td>${bool(r.volume_structure_ok)}</td>
        <td>${r.status}</td><td>${r.reasons}</td>
      </tr>`).join('')+'</tbody></table></div>'
  }

  function num(v){return v===null||v===undefined?'-':Number(v).toFixed(3)}
  function bool(v){return v===true?'是':v===false?'否':'-'}

  function ensureDiagPanel(){
    if($('diagPanel')||!$('view-run')) return;
    const panel=document.createElement('div');
    panel.id='diagPanel';
    panel.className='panel diag-panel';
    panel.innerHTML=`
      <div class="panel-head split">
        <h3>2560 摸底指标明细</h3>
        <button id="loadDiagBtn" class="ghost">查看当前筛选指标</button>
      </div>
      <div id="diagSummary" class="diag-summary">
        即使 signals=0，也可查看每只股票的 30m / MA25 / 量能 / 未命中原因。
      </div>
      <div id="diagTable"></div>
    `;
    $('view-run').appendChild(panel);
    $('loadDiagBtn').onclick=loadDiagnostics;
  }

  async function loadDiagnostics(){
    const mt=$('marketTypeFilter')?$('marketTypeFilter').value:'all';
    const q=$('stockSearch')?$('stockSearch').value.trim():'';
    const limit=prompt('加载多少只股票的摸底指标？建议先 500，最多 5000。','500')||'500';
    $('diagSummary').textContent='正在加载摸底指标...';
    try{
      const d=await api('/api/strategy/2560/probe-indicators?market_type='+encodeURIComponent(mt)+'&limit='+encodeURIComponent(limit)+(q?'&q='+encodeURIComponent(q):''));
      const s=d.summary||{};
      $('diagSummary').textContent=`总数 ${s.total||0}；缺30m ${s.missing_30m||0}；缺日线 ${s.missing_daily||0}；基础条件满足 ${s.base_ok||0}`;
      renderDiagTable(d.items||[]);
    }catch(e){$('diagSummary').textContent='加载失败：'+e.message}
  }

  const oldRefresh=window.refresh;
  function hook(){ensureDiagPanel()}
  document.addEventListener('click',()=>setTimeout(hook,50));
  setTimeout(hook,500);
})();
```

---

### B.6 `app/static/styles.diagnostic.css` — 诊断面板样式

```css
.diag-controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.diag-controls input,.diag-controls select{min-width:150px}
.diag-cards{grid-template-columns:repeat(5,minmax(120px,1fr))}
.diag-bar{display:flex;flex-direction:column;gap:9px}
.diag-bar-row{display:grid;grid-template-columns:150px 1fr 52px;gap:10px;align-items:center;font-size:13px}
.diag-bar-bg{height:12px;border-radius:999px;background:#e5e7eb;overflow:hidden}
.diag-bar-bg div{height:100%}
.diag-pie{width:190px;height:190px;border-radius:50%;background:#e5e7eb;margin:auto}
.diag-legend{display:grid;gap:6px;margin-top:12px;font-size:13px}
.diag-legend div{display:flex;gap:8px;align-items:center}
.diag-legend i{display:inline-block;width:12px;height:12px;border-radius:3px}
.diag-near td{background:#ecfdf5!important}
.diag-empty{padding:14px;color:#64748b}
.diag-table table,.diag-panel table{font-size:12px}
.diag-table th,.diag-table td{padding:8px 10px;white-space:nowrap}
@media(max-width:1100px){.diag-cards{grid-template-columns:repeat(2,1fr)}}
```

---

### B.7 `app/static/styles.diagnostic-menu.css`

```css
.diag-panel{margin-top:16px;border:1px solid #c7d2fe;background:#f8fafc}
.diag-summary{font-size:13px;color:#475569;margin-bottom:10px}
.diag-empty{padding:12px;color:#64748b}
.diag-panel table{font-size:12px}
.diag-panel th,.diag-panel td{padding:8px 10px;white-space:nowrap}
```

---

### B.8 `app/static/styles.market-filter.css` — 市场筛选样式

```css
/* market filter patch */
#marketTypeFilter{min-width:150px;border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff;font-family:inherit}
.stock-row.selected td{background:#dbeafe!important}
```

---

### B.9 `app/static/styles.market-probe.css` — 摸底面板样式

```css
/* market probe patch */
.probe-panel{border:1px solid #bfdbfe;background:#eff6ff}
.probe-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.probe-btn{border:0;border-radius:10px;padding:10px 14px;cursor:pointer;font-weight:700;background:#2563eb;color:#fff}
.probe-btn:hover{background:#1d4ed8}
.probe-btn.danger{background:#0f172a}
.probe-btn.danger:hover{background:#1e293b}
.probe-note{color:#475569;font-size:13px}
#probeLimit{min-width:210px}
```

---

## 附录 C — 前端菜单 Wiring 逻辑详解

### C.1 侧边栏导航路由机制

`app.js` 中的核心 wiring 代码 (文件末尾):

```javascript
// 1. 选中所有 .nav-item 按钮
document.querySelectorAll('.nav-item').forEach(b => b.addEventListener('click', async () => {
  // 2. 清除所有按钮的 active 样式
  document.querySelectorAll('.nav-item').forEach(x => x.classList.remove('active'));
  // 3. 当前按钮加 active
  b.classList.add('active');
  // 4. 隐藏所有 view 区域
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  // 5. 读取 data-view 属性，切换对应区域
  state.view = b.dataset.view;
  state.page = 1;                       // 重置分页
  $('view-' + state.view).classList.add('active');
  // 6. 更新标题/副标题
  $('pageTitle').textContent = titles[state.view][0];
  $('pageSubtitle').textContent = titles[state.view][1];
  // 7. 按需加载数据
  await refresh();
}));
```

### C.2 视图标题映射

```javascript
const titles = {
  overview:    ['总览',   '查看最新批次、结构完整率、标签分布与系统状态'],
  run:         ['入库计算', '支持选择股票、全选、sh/sz 全部摸底计算'],
  diagnostics: ['摸底指标', '查看2560各项指标、未命中原因统计，以及接近满足条件的股票'],
  signals:     ['信号列表', '逐条查看2560结构条件、标签与解释'],
  complete:    ['完整结构', '查看最近结构完整案例及后续表现'],
  statistics:  ['结构统计', '按结构状态、标签、行业、板块、概念统计'],
  batches:     ['批次管理', '查看分析批次、版本、运行状态'],
  quality:     ['数据质量', '查看日线/分钟线完整性与异常情况']
};
```

### C.3 按钮事件绑定全景图

| 按钮 ID | 触发函数 | 所属视图 |
|---------|---------|---------|
| `refreshBtn` | `refresh()` | 全局 |
| `searchStockBtn` | `loadStocks()` | 入库计算 |
| `selectCurrentBtn` | `selectCurrentStocks()` | 入库计算 |
| `selectByFilterBtn` | `selectByFilterLimit()` | 入库计算 |
| `runSelectedBtn` | `runSelected()` | 入库计算 |
| `clearSelectedBtn` | 清空选择 + 重置 | 入库计算 |
| `probeShBtn` | `runProbe('sh')` | 入库计算 |
| `probeSzBtn` | `runProbe('sz')` | 入库计算 |
| `probeAllBtn` | `runProbe('all')` | 入库计算 |
| `diagLoadBtn` | `loadDiagnostics()` | 摸底指标 |
| `applySignalFilter` | 重置分页 + `loadSignals()` | 信号列表 |
| `prevPage` | 上一页 `loadSignals()` | 信号列表 |
| `nextPage` | 下一页 `loadSignals()` | 信号列表 |
| `statType` (onchange) | `loadStatistics()` | 结构统计 |
| `closeDrawer` | 隐藏详情抽屉 | 全局 |

### C.4 refresh() 数据加载分发

```javascript
async function refresh() {
  await loadHealth();                                    // 总是执行
  if(state.view === 'overview')    await loadOverview();
  if(state.view === 'run')         await loadStocks();
  if(state.view === 'diagnostics') await loadDiagnostics();
  if(state.view === 'signals')     await loadSignals();
  if(state.view === 'complete')    await loadComplete();
  if(state.view === 'statistics')  await loadStatistics();
  if(state.view === 'batches')     await loadBatches();
  if(state.view === 'quality')     await loadQuality();
}
```

### C.5 动态注入 — diagnostic_menu_append.js

此脚本实现了"渐进增强"：

1. **防重入**: `window.__strategy2560DiagnosticMenuInstalled` 标志位
2. **按钮注入**: 在侧边栏 `.nav` 的第 3 个位置插入 "摸底指标" 按钮 (`diagNavBtn`)
3. **区域注入**: 在 `.main` 末尾追加 `<section id="view-diagnostics">` 完整 HTML
4. **初始化**: `setTimeout(ensureDiagView, 300)` + 全局 click 监听兜底

这使得即使 HTML 中不包含 diagnostics 区域，脚本也能在运行时动态补全。

### C.6 增量注入 — diagnostic_append.js

此脚本在 "入库计算" 视图 (`view-run`) 底部追加一个诊断面板 (`diagPanel`)，让用户可以在选股执行计算的同时，查看当前筛选下股票的摸底指标状态，无需切换到独立视图。

---

> **免责声明**: 本系统仅用于结构化行情分析与历史复盘，不构成任何投资建议。
