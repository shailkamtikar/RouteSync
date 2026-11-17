"""Shared helpers for the operator scripts: an API client and the signed-in operator session."""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
api_env = dotenv_values(ROOT / "apps" / "api" / ".env")
web_env = dotenv_values(ROOT / "apps" / "web" / ".env.local")
DEFAULT_API = "http://127.0.0.1:8010"
DEFAULT_WEB = "http://localhost:3000"


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = ""
        self.refresh_token = ""

    def call(
        self,
        method: str,
        path: str,
        body=None,
        *,
        absolute=False,
        headers=None,
        optional=False,
    ):
        url = path if absolute else f"{self.base}/api/v1{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if optional and exc.code == 404:
                return None
            detail = exc.read().decode(errors="replace")[:300]
            sys.exit(f"{method} {path} failed: HTTP {exc.code} {detail}")

    def sign_in(self, email: str) -> None:
        """Password sign-in with the seeded test account, as the web app does."""
        auth = f"{api_env['SUPABASE_URL'].rstrip('/')}/auth/v1/token"
        session = self.call(
            "POST",
            f"{auth}?grant_type=password",
            {"email": email, "password": api_env["SEED_USER_PASSWORD"]},
            absolute=True,
            headers={"apikey": web_env["NEXT_PUBLIC_SUPABASE_ANON_KEY"]},
        )
        self.token = session["access_token"]
        self.refresh_token = session["refresh_token"]

    def refresh(self) -> None:
        auth = f"{api_env['SUPABASE_URL'].rstrip('/')}/auth/v1/token"
        session = self.call(
            "POST",
            f"{auth}?grant_type=refresh_token",
            {"refresh_token": self.refresh_token},
            absolute=True,
            headers={"apikey": web_env["NEXT_PUBLIC_SUPABASE_ANON_KEY"]},
        )
        self.token = session["access_token"]
        self.refresh_token = session["refresh_token"]


def signed_in(api: str, email: str) -> Client:
    client = Client(api)
    client.sign_in(email)
    return client
