"""Remove all operator data from the DEV database, keeping operators and their members.

Journeys and audit events cannot be deleted through the application, so test runs leave
rows behind. This script truncates the data tables so the dev project starts clean.

Usage (from the repo root):
    apps/api/.venv/Scripts/python scripts/reset_dev_data.py --yes
"""

import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[1] / "apps" / "api" / ".env"
KEEP = {"operators", "operator_members"}


def main() -> None:
    if "--yes" not in sys.argv:
        sys.exit("This deletes all journeys, bookings, buses and services. Re-run with --yes.")
    url = dotenv_values(ENV_FILE)["DATABASE_URL"]
    with psycopg.connect(url, connect_timeout=15) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "select tablename from pg_tables where schemaname = 'public' order by 1"
            )
            if row[0] not in KEEP
        ]
        quoted = ", ".join(f'public."{name}"' for name in tables)
        conn.execute(f"truncate table {quoted} restart identity cascade")
        members = conn.execute("select count(*) from public.operator_members").fetchone()[0]
        conn.commit()
    print(f"cleared {len(tables)} tables; kept {members} operator members")


if __name__ == "__main__":
    main()
