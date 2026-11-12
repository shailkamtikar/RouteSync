"""Seed the dev project with test operators and users. Safe to run repeatedly.

Usage (from the repo root):
    apps/api/.venv/Scripts/python scripts/seed_dev.py

Reads SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL and SEED_USER_PASSWORD from
apps/api/.env. If SEED_USER_PASSWORD is missing, a random one is generated and appended to
that file. The password is never printed.
"""

import json
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[1] / "apps" / "api" / ".env"

OPERATORS = {
    "Shivneri Travels": [("owner1@routesync.test", "owner"), ("dispatcher1@routesync.test", "dispatcher")],
    "Deccan Express": [("owner2@routesync.test", "owner")],
}


def load_env() -> dict[str, str]:
    env = dict(dotenv_values(ENV_FILE))
    if not env.get("SEED_USER_PASSWORD"):
        env["SEED_USER_PASSWORD"] = secrets.token_urlsafe(18)
        with ENV_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"\n# Password shared by the seeded test users\nSEED_USER_PASSWORD={env['SEED_USER_PASSWORD']}\n")
    return env


def ensure_user(env: dict[str, str], conn: psycopg.Connection, email: str) -> str:
    row = conn.execute("select id from auth.users where email = %s", (email,)).fetchone()
    if row:
        return str(row[0])
    key = env["SUPABASE_SERVICE_ROLE_KEY"]
    request = urllib.request.Request(
        f"{env['SUPABASE_URL'].rstrip('/')}/auth/v1/admin/users",
        data=json.dumps(
            {"email": email, "password": env["SEED_USER_PASSWORD"], "email_confirm": True}
        ).encode(),
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())["id"]
    except urllib.error.HTTPError as exc:
        sys.exit(f"could not create {email}: HTTP {exc.code}")


def main() -> None:
    env = load_env()
    with psycopg.connect(env["DATABASE_URL"], connect_timeout=15) as conn:
        for name, members in OPERATORS.items():
            row = conn.execute("select id from public.operators where name = %s", (name,)).fetchone()
            operator_id = row[0] if row else conn.execute(
                "insert into public.operators (name) values (%s) returning id", (name,)
            ).fetchone()[0]
            for email, role in members:
                user_id = ensure_user(env, conn, email)
                conn.execute(
                    "insert into public.operator_members (operator_id, user_id, role) "
                    "values (%s, %s, %s) on conflict (user_id) do nothing",
                    (operator_id, user_id, role),
                )
                print(f"ok: {email} -> {name} ({role})")
        conn.commit()


if __name__ == "__main__":
    main()
