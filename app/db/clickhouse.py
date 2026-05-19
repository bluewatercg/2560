from __future__ import annotations

from typing import Any
import httpx

from app.core.config import get_settings

class ClickHouseClient:
    """Minimal ClickHouse client using HTTP interface."""

    def __init__(self):
        settings = get_settings()
        self.url = settings.clickhouse_url
        self.database = settings.CLICKHOUSE_DATABASE
        self.user = settings.CLICKHOUSE_USER
        self.password = settings.CLICKHOUSE_PASSWORD

    def _params(self, query: str) -> dict:
        params = {"query": query, "database": self.database, "user": self.user}
        if self.password:
            params["password"] = self.password
        return params

    def command(self, query: str) -> Any:
        """Execute a command (CREATE, INSERT, DROP, etc.)."""
        with httpx.Client(timeout=30) as client:
            r = client.post(self.url, params=self._params(query))
            r.raise_for_status()
            return r.text.strip()

    def query(self, query: str, fmt: str = "JSONEachRow") -> list[dict]:
        """Execute a SELECT query, return list of dicts."""
        query_with_fmt = f"{query.rstrip(';')} FORMAT {fmt}"
        with httpx.Client(timeout=60) as client:
            r = client.post(self.url, params=self._params(query_with_fmt))
            r.raise_for_status()
            if not r.text.strip():
                return []
            import json
            return json.loads(r.text)

    def query_one(self, query: str) -> dict | None:
        """Execute a SELECT query, return first row or None."""
        rows = self.query(query)
        return rows[0] if rows else None

    def insert_batch(self, table: str, data: list[dict]) -> int:
        """Batch insert rows into a table using Native JSONEachRow format."""
        if not data:
            return 0
        import json
        body = "\n".join(json.dumps(row, default=str) for row in data)
        query = f"INSERT INTO {self.database}.{table} FORMAT JSONEachRow"
        params = {"database": self.database, "user": self.user, "query": query}
        if self.password:
            params["password"] = self.password
        with httpx.Client(timeout=120) as client:
            r = client.post(self.url, params=params, content=body.encode("utf-8"),
                           headers={"Content-Type": "application/x-ndjson"})
            r.raise_for_status()
        return len(data)

    def ping(self) -> bool:
        """Check if ClickHouse is reachable."""
        try:
            with httpx.Client(timeout=5) as client:
                r = client.post(self.url, params=self._params("SELECT 1"))
                return r.status_code == 200 and r.text.strip() == "1"
        except Exception:
            return False

    def count(self, table: str) -> int:
        """Get row count for a table."""
        result = self.query_one(f"SELECT count() AS cnt FROM {table}")
        return int(result["cnt"]) if result else 0


# Global singleton
_clickhouse_client: ClickHouseClient | None = None

def get_clickhouse() -> ClickHouseClient:
    global _clickhouse_client
    if _clickhouse_client is None:
        _clickhouse_client = ClickHouseClient()
    return _clickhouse_client
