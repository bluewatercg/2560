from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()

# Lazy engine — don't connect at import time
_engine = None
_SessionLocal = None

def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.sqlalchemy_url,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=max(settings.DB_POOL_SIZE, 10),
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
        )
    return _engine

def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_get_engine(), future=True)
    return _SessionLocal()

def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()

# Backwards-compatible alias for background scripts
SessionLocal = get_session

def ping_database() -> bool:
    try:
        with _get_engine().connect() as conn:
            return conn.execute(text('SELECT 1')).scalar_one() == 1
    except Exception:
        return False
