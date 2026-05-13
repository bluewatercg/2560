from __future__ import annotations

SUPPORTED_MARKET_SCOPES = ("sh60", "sh68", "sz00", "sz30")

MARKET_PREFIXES: dict[str, tuple[str, ...]] = {
    "sh60": ("sh.60",),
    "sh68": ("sh.68",),
    "sz00": ("sz.00",),
    "sz30": ("sz.30",),
    "sh": ("sh.60", "sh.68"),
    "sz": ("sz.00", "sz.30"),
    "all": ("sh.60", "sh.68", "sz.00", "sz.30"),
    "": ("sh.60", "sh.68", "sz.00", "sz.30"),
}

FILE_PREFIXES: dict[str, tuple[str, ...]] = {
    key: tuple(prefix.replace(".", "") for prefix in prefixes)
    for key, prefixes in MARKET_PREFIXES.items()
}


def normalize_market_scope(market: str | None) -> str:
    return (market or "all").lower().strip()


def market_prefixes(market: str | None) -> tuple[str, ...]:
    return MARKET_PREFIXES.get(normalize_market_scope(market), MARKET_PREFIXES["all"])


def market_file_prefixes(market: str | None) -> tuple[str, ...]:
    return FILE_PREFIXES.get(normalize_market_scope(market), FILE_PREFIXES["all"])


def market_sql_where(column: str, market: str | None) -> str:
    prefixes = market_prefixes(market)
    clauses = [f"{column} LIKE '{prefix}%'" for prefix in prefixes]
    return clauses[0] if len(clauses) == 1 else "(" + " OR ".join(clauses) + ")"
