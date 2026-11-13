"""End-to-end auth smoke test against a running local API and the dev Supabase project.

Signs each seeded user in with the password grant, then calls GET /api/v1/me.
Usage: start the API on :8000, then run this script with the API virtualenv.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
api_env = dotenv_values(ROOT / "apps" / "api" / ".env")
web_env = dotenv_values(ROOT / "apps" / "web" / ".env.local")
API = "http://127.0.0.1:8000"

EXPECTED = {
    "owner1@routesync.test": ("Shivneri Travels", "owner"),
    "dispatcher1@routesync.test": ("Shivneri Travels", "dispatcher"),
    "owner2@routesync.test": ("Deccan Express", "owner"),
}


def call(url: str, *, headers: dict, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def sign_in(email: str) -> str:
    status, body = call(
        f"{api_env['SUPABASE_URL'].rstrip('/')}/auth/v1/token?grant_type=password",
        headers={
            "apikey": web_env["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
            "Content-Type": "application/json",
        },
        body={"email": email, "password": api_env["SEED_USER_PASSWORD"]},
    )
    if status != 200:
        sys.exit(f"FAIL sign-in {email}: HTTP {status}")
    return body["access_token"]


failures = 0
for email, (operator, role) in EXPECTED.items():
    token = sign_in(email)
    status, me = call(f"{API}/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    ok = (
        status == 200 and me.get("operator_name") == operator and me.get("role") == role
    )
    failures += not ok
    verdict = "PASS" if ok else "FAIL"
    print(
        f"{verdict} {email}: HTTP {status} {me.get('operator_name')} {me.get('role')}"
    )

status, _ = call(f"{API}/api/v1/me", headers={})
print(f"{'PASS' if status == 401 else 'FAIL'} no token: HTTP {status}")
failures += status != 401
status, _ = call(
    f"{API}/api/v1/me", headers={"Authorization": "Bearer " + token[:-4] + "AAAA"}
)
print(f"{'PASS' if status == 401 else 'FAIL'} tampered signature: HTTP {status}")
failures += status != 401
sys.exit(1 if failures else 0)
