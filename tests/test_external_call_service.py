from __future__ import annotations

from datetime import date, datetime, timedelta
import importlib.util
from pathlib import Path
import sys

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/external_call_service.py"
SPEC = importlib.util.spec_from_file_location("external_call_service", MODULE_PATH)
external_call_service = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = external_call_service
SPEC.loader.exec_module(external_call_service)

ExternalCallResult = external_call_service.ExternalCallResult
ExternalCallService = external_call_service.ExternalCallService
InvalidExternalCacheTTL = external_call_service.InvalidExternalCacheTTL


NOW = datetime(2026, 6, 9, 10, 30, 0)


class FakeExternalCallRepository:
    def __init__(self):
        self.caches = {}
        self.budgets = {}
        self.logs = []
        self.deleted_cache_keys = []

    def get_cache(self, cache_key: str):
        return self.caches.get(cache_key)

    def upsert_cache(self, cache_key: str, provider: str, payload, ttl_hours, expire_at, now):
        self.caches[cache_key] = {
            "cache_key": cache_key,
            "provider": provider,
            "payload": payload,
            "ttl_hours": ttl_hours,
            "expire_at": expire_at,
            "updated_at": now,
        }

    def update_cache_ttl(self, cache_key: str, ttl_hours, expire_at, now):
        self.caches[cache_key]["ttl_hours"] = ttl_hours
        self.caches[cache_key]["expire_at"] = expire_at
        self.caches[cache_key]["updated_at"] = now

    def delete_cache(self, cache_key: str):
        self.deleted_cache_keys.append(cache_key)
        self.caches.pop(cache_key, None)

    def get_budget(self, budget_key: str):
        return self.budgets.get(budget_key)

    def upsert_budget(self, budget_key: str, daily_limit: int, today_used: int, reset_at: date, now):
        self.budgets[budget_key] = {
            "budget_key": budget_key,
            "daily_limit": daily_limit,
            "today_used": today_used,
            "reset_at": reset_at,
            "updated_at": now,
        }

    def write_log(self, provider: str, cache_key: str, status: str, message: str = "", meta=None, now=None):
        self.logs.append(
            {
                "provider": provider,
                "cache_key": cache_key,
                "status": status,
                "message": message,
                "meta": meta or {},
                "created_at": now,
            }
        )


def make_service(repo: FakeExternalCallRepository | None = None) -> ExternalCallService:
    return ExternalCallService(repo or FakeExternalCallRepository(), clock=lambda: NOW)


def test_positive_ttl_and_future_expire_at_is_cache_hit_without_budget_increment():
    repo = FakeExternalCallRepository()
    repo.caches["eastmoney:topics"] = {
        "cache_key": "eastmoney:topics",
        "provider": "eastmoney",
        "payload": {"topics": ["AI"]},
        "ttl_hours": 2,
        "expire_at": NOW + timedelta(minutes=1),
    }
    repo.budgets["eastmoney"] = {
        "budget_key": "eastmoney",
        "daily_limit": 10,
        "today_used": 4,
        "reset_at": NOW.date(),
    }
    service = make_service(repo)

    result = service.call(
        provider="eastmoney",
        cache_key="eastmoney:topics",
        ttl_hours=2,
        daily_limit=10,
        fetcher=lambda: pytest.fail("cache hit must not call provider"),
    )

    assert result == ExternalCallResult(status="cache_hit", data={"topics": ["AI"]}, from_cache=True)
    assert repo.budgets["eastmoney"]["today_used"] == 4


@pytest.mark.parametrize("cached_ttl", [None, 0, -1])
def test_non_positive_or_null_cached_ttl_is_not_a_cache_hit(cached_ttl):
    repo = FakeExternalCallRepository()
    repo.caches["cninfo:audit"] = {
        "cache_key": "cninfo:audit",
        "provider": "cninfo",
        "payload": {"old": True},
        "ttl_hours": cached_ttl,
        "expire_at": NOW + timedelta(days=1),
    }
    service = make_service(repo)

    result = service.call(
        provider="cninfo",
        cache_key="cninfo:audit",
        ttl_hours=1,
        daily_limit=10,
        fetcher=lambda: {"fresh": True},
    )

    assert result.status == "success"
    assert result.data == {"fresh": True}
    assert repo.budgets["cninfo"]["today_used"] == 1
    assert [log["status"] for log in repo.logs] == ["cache_miss", "success"]


def test_expired_cache_record_is_not_a_cache_hit():
    repo = FakeExternalCallRepository()
    repo.caches["cninfo:expired"] = {
        "cache_key": "cninfo:expired",
        "provider": "cninfo",
        "payload": {"old": True},
        "ttl_hours": 2,
        "expire_at": NOW - timedelta(seconds=1),
    }
    service = make_service(repo)

    result = service.call(
        provider="cninfo",
        cache_key="cninfo:expired",
        ttl_hours=1,
        daily_limit=10,
        fetcher=lambda: {"fresh": True},
    )

    assert result.status == "success"
    assert result.data == {"fresh": True}


def test_negative_ttl_for_new_external_call_is_rejected():
    service = make_service()

    with pytest.raises(InvalidExternalCacheTTL, match="ttl_hours"):
        service.call(
            provider="cninfo",
            cache_key="cninfo:invalid",
            ttl_hours=-1,
            daily_limit=10,
            fetcher=lambda: {"never": "called"},
        )


def test_budget_resets_before_external_call_when_reset_at_is_before_today():
    repo = FakeExternalCallRepository()
    repo.budgets["eastmoney"] = {
        "budget_key": "eastmoney",
        "daily_limit": 5,
        "today_used": 5,
        "reset_at": date(2026, 6, 8),
    }
    service = make_service(repo)

    result = service.call(
        provider="eastmoney",
        cache_key="eastmoney:reset",
        ttl_hours=1,
        daily_limit=5,
        fetcher=lambda: {"ok": True},
    )

    assert result.status == "success"
    assert repo.budgets["eastmoney"]["reset_at"] == NOW.date()
    assert repo.budgets["eastmoney"]["today_used"] == 1


def test_budget_exceeded_returns_clear_status_and_writes_log_without_calling_provider():
    repo = FakeExternalCallRepository()
    repo.budgets["cninfo"] = {
        "budget_key": "cninfo",
        "daily_limit": 2,
        "today_used": 2,
        "reset_at": NOW.date(),
    }
    service = make_service(repo)

    result = service.call(
        provider="cninfo",
        cache_key="cninfo:blocked",
        ttl_hours=1,
        daily_limit=2,
        fetcher=lambda: pytest.fail("budget exceeded must not call provider"),
    )

    assert result.status == "budget_exceeded"
    assert result.error == "external call budget exceeded"
    assert repo.logs[-1]["status"] == "budget_exceeded"
    assert repo.budgets["cninfo"]["today_used"] == 2


def test_cache_miss_success_logs_and_persists_cache_with_expire_at():
    repo = FakeExternalCallRepository()
    service = make_service(repo)

    result = service.call(
        provider="cninfo",
        cache_key="cninfo:notice",
        ttl_hours=3,
        daily_limit=10,
        fetcher=lambda: {"notice": "ok"},
    )

    assert result == ExternalCallResult(status="success", data={"notice": "ok"}, from_cache=False)
    assert repo.caches["cninfo:notice"]["payload"] == {"notice": "ok"}
    assert repo.caches["cninfo:notice"]["ttl_hours"] == 3
    assert repo.caches["cninfo:notice"]["expire_at"] == NOW + timedelta(hours=3)
    assert [log["status"] for log in repo.logs] == ["cache_miss", "success"]


def test_external_call_error_is_logged_and_counts_against_budget():
    repo = FakeExternalCallRepository()
    service = make_service(repo)

    result = service.call(
        provider="cninfo",
        cache_key="cninfo:error",
        ttl_hours=1,
        daily_limit=10,
        fetcher=lambda: (_ for _ in ()).throw(RuntimeError("403 Forbidden")),
    )

    assert result.status == "error"
    assert result.error == "403 Forbidden"
    assert repo.budgets["cninfo"]["today_used"] == 1
    assert [log["status"] for log in repo.logs] == ["cache_miss", "error"]


def test_invalidate_cache_only_expires_record_without_deleting_it():
    repo = FakeExternalCallRepository()
    repo.caches["eastmoney:topics"] = {
        "cache_key": "eastmoney:topics",
        "provider": "eastmoney",
        "payload": {"topics": ["AI"]},
        "ttl_hours": 4,
        "expire_at": NOW + timedelta(hours=4),
    }
    service = make_service(repo)

    assert service.invalidate_cache("eastmoney:topics") is True

    assert repo.caches["eastmoney:topics"]["ttl_hours"] == 0
    assert repo.caches["eastmoney:topics"]["expire_at"] == NOW
    assert repo.deleted_cache_keys == []
