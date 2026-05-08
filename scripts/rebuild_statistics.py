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
