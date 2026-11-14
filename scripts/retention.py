"""Apply data retention on the database. Safe to run on a schedule (daily).

Usage:
    python scripts/retention.py [--gps-days 30] [--manifest-days 30] [--snapshot-days 7] [--dry-run]

Reads DATABASE_URL from apps/api/.env (or the environment). Retention periods are a product
and legal decision; the defaults here are placeholders.
"""

import argparse
import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[1] / "apps" / "api" / ".env"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gps-days", type=int, default=30)
    parser.add_argument("--manifest-days", type=int, default=30)
    parser.add_argument("--snapshot-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL") or dotenv_values(ENV_FILE).get("DATABASE_URL")
    with psycopg.connect(url, connect_timeout=15) as conn:
        gps, snapshots, passengers = conn.execute(
            "select * from app.apply_retention(%s, %s, %s)",
            (args.gps_days, args.manifest_days, args.snapshot_days),
        ).fetchone()
        if args.dry_run:
            conn.rollback()
            print(f"dry run: would remove {gps} positions, {snapshots} snapshots, {passengers} passenger records")
        else:
            conn.commit()
            print(f"removed {gps} positions, {snapshots} snapshots, {passengers} passenger records")


if __name__ == "__main__":
    main()
