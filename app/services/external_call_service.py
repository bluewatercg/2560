from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Protocol


class InvalidExternalCacheTTL(ValueError):
    """Raised when callers attempt to create a cache record with invalid TTL."""


@dataclass(frozen=True)
class ExternalCallResult:
    status: str
    data: Any = None
    from_cache: bool = False
    error: str | None = None


class ExternalCallRepository(Protocol):
    def get_cache(self, cache_key: str) -> Any: ...

    def upsert_cache(
        self,
        cache_key: str,
        provider: str,
        payload: Any,
        ttl_hours: int | None,
        expire_at: datetime | None,
        now: datetime,
    ) -> None: ...

    def update_cache_ttl(self, cache_key: str, ttl_hours: int, expire_at: datetime, now: datetime) -> None: ...

    def get_budget(self, budget_key: str) -> Any: ...

    def upsert_budget(self, budget_key: str, daily_limit: int, today_used: int, reset_at: date, now: datetime) -> None: ...

    def write_log(
        self,
        provider: str,
        cache_key: str,
        status: str,
        message: str = "",
        meta: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None: ...


class ExternalCallService:
    def __init__(self, repository: ExternalCallRepository, clock: Callable[[], datetime] | None = None):
        self.repository = repository
        self.clock = clock or datetime.now

    def call(
        self,
        *,
        provider: str,
        cache_key: str,
        ttl_hours: int | None,
        daily_limit: int,
        fetcher: Callable[[], Any],
        budget_key: str | None = None,
    ) -> ExternalCallResult:
        self._validate_ttl_for_write(ttl_hours)
        now = self.clock()

        cache = self.repository.get_cache(cache_key)
        if self._is_cache_hit(cache, now):
            return ExternalCallResult(status="cache_hit", data=self._field(cache, "payload"), from_cache=True)

        self._write_log(provider, cache_key, "cache_miss", now=now)

        effective_budget_key = budget_key or provider
        budget = self._prepare_budget(effective_budget_key, daily_limit, now)
        if int(self._field(budget, "today_used", 0) or 0) >= int(self._field(budget, "daily_limit", daily_limit) or daily_limit):
            self._write_log(
                provider,
                cache_key,
                "budget_exceeded",
                message="external call budget exceeded",
                meta={"budget_key": effective_budget_key},
                now=now,
            )
            return ExternalCallResult(
                status="budget_exceeded",
                from_cache=False,
                error="external call budget exceeded",
            )

        self._set_budget_used(
            effective_budget_key,
            int(self._field(budget, "daily_limit", daily_limit) or daily_limit),
            int(self._field(budget, "today_used", 0) or 0) + 1,
            now.date(),
            now,
        )

        try:
            data = fetcher()
        except Exception as exc:
            self._write_log(provider, cache_key, "error", message=str(exc), now=now)
            return ExternalCallResult(status="error", from_cache=False, error=str(exc))

        self.repository.upsert_cache(
            cache_key,
            provider,
            data,
            ttl_hours,
            self._expire_at(ttl_hours, now),
            now,
        )
        self._write_log(provider, cache_key, "success", now=now)
        return ExternalCallResult(status="success", data=data, from_cache=False)

    def invalidate_cache(self, cache_key: str) -> bool:
        now = self.clock()
        cache = self.repository.get_cache(cache_key)
        if cache is None:
            return False
        self.repository.update_cache_ttl(cache_key, ttl_hours=0, expire_at=now, now=now)
        return True

    def _prepare_budget(self, budget_key: str, daily_limit: int, now: datetime) -> Any:
        today = now.date()
        budget = self.repository.get_budget(budget_key)
        if budget is None:
            self._set_budget_used(budget_key, daily_limit, 0, today, now)
            return {
                "budget_key": budget_key,
                "daily_limit": daily_limit,
                "today_used": 0,
                "reset_at": today,
            }

        reset_at = self._field(budget, "reset_at")
        if reset_at is None or reset_at < today:
            effective_limit = int(self._field(budget, "daily_limit", daily_limit) or daily_limit)
            self._set_budget_used(budget_key, effective_limit, 0, today, now)
            return {
                "budget_key": budget_key,
                "daily_limit": effective_limit,
                "today_used": 0,
                "reset_at": today,
            }
        return budget

    def _set_budget_used(self, budget_key: str, daily_limit: int, today_used: int, reset_at: date, now: datetime) -> None:
        self.repository.upsert_budget(budget_key, daily_limit, today_used, reset_at, now)

    def _write_log(
        self,
        provider: str,
        cache_key: str,
        status: str,
        message: str = "",
        meta: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        self.repository.write_log(provider, cache_key, status, message=message, meta=meta, now=now or self.clock())

    @staticmethod
    def _validate_ttl_for_write(ttl_hours: int | None) -> None:
        if ttl_hours is not None and ttl_hours < 0:
            raise InvalidExternalCacheTTL("ttl_hours must be NULL, 0, or a positive integer")

    @classmethod
    def _is_cache_hit(cls, cache: Any, now: datetime) -> bool:
        ttl_hours = cls._field(cache, "ttl_hours")
        expire_at = cls._field(cache, "expire_at")
        return ttl_hours is not None and ttl_hours > 0 and expire_at is not None and expire_at > now

    @staticmethod
    def _expire_at(ttl_hours: int | None, now: datetime) -> datetime | None:
        if ttl_hours is None:
            return None
        if ttl_hours == 0:
            return now
        return now + timedelta(hours=ttl_hours)

    @staticmethod
    def _field(record: Any, name: str, default: Any = None) -> Any:
        if record is None:
            return default
        if isinstance(record, dict):
            return record.get(name, default)
        return getattr(record, name, default)
