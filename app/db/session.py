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
