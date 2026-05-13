import argparse
from sqlalchemy import text

from app.core.market_scope import market_sql_where
from app.db.session import SessionLocal
from app.services.signal_engine_2560 import SignalEngine2560
from app.services.statistics_engine import StatisticsEngine


def market_where(market_type: str) -> str:
    return market_sql_where("code", market_type)


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
