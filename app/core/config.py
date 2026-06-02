from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # MySQL (legacy - job queue, import tracking)
    DB_HOST: str = '192.168.1.254'
    DB_PORT: int = 3306
    DB_USER: str = 'watchlist_decision_support'
    DB_PASSWORD: str = ''
    DB_NAME: str = 'watchlist_decision_support'
    DB_POOL_SIZE: int = 20

    # ClickHouse (market data storage)
    CLICKHOUSE_HOST: str = '192.168.1.30'
    CLICKHOUSE_PORT: int = 8123
    CLICKHOUSE_USER: str = 'default'
    CLICKHOUSE_PASSWORD: str = ''
    CLICKHOUSE_DATABASE: str = 'strategy2560'

    APP_HOST: str = '0.0.0.0'
    APP_PORT: int = 8000
    APP_ENV: str = 'local'
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    @property
    def sqlalchemy_url(self) -> str:
        return f'mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4'

    @property
    def clickhouse_url(self) -> str:
        return f'http://{self.CLICKHOUSE_HOST}:{self.CLICKHOUSE_PORT}'

@lru_cache
def get_settings() -> Settings:
    return Settings()
