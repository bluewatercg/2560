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
