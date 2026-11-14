# Security review

Last run: November 2026, Phase 9.

## What is enforced

| Area | Mechanism | Verified by |
|---|---|---|
| Operator isolation | Every query filters by the operator resolved from the verified sign-in token; row level security on every table as a second line | Generated authorization matrix (177 checks across every operator endpoint): 401 without a token, 403 without a membership, 404 for another operator's resources, owner-only actions refused to dispatchers |
| Sign-in tokens | Asymmetric (ES256) tokens verified against the project's published keys; expiry, audience, issuer and role checked; `alg=none` and shared-secret tokens rejected | `tests/test_auth.py`, `tests/test_jwks_resilience.py` |
| Public tracking links | 256-bit random tokens; only a peppered hash is stored; revocable; expire 24 h after scheduled arrival; rate-limited per address and per link | `tests/db/test_public_track.py` |
| Public data | Explicit allowlist view; passenger names, seats, phones, references and manifests never leave the backend | Privacy assertions in public, monitor, Companion tool and chat tests |
| Device tokens | Per-journey, hashed, revocable; the journey comes from the token, never the request | `tests/db/test_gps_ingest.py` |
| Assistant | Fixed read-only tool set, journey bound server-side, arguments validated, answers scrubbed for private strings, throttled | `tests/db/test_companion_chat.py`, live evaluation (adversarial 7/7, 0 leaks) |
| Secrets | Server-side environment only; browser receives only the public map and anon keys | gitleaks over the full history: no leaks; only `.env.example` is tracked |
| Headers | `nosniff`, `no-referrer`, `DENY` framing, restrictive CSP, server header removed | `tests/test_security_headers.py` |
| Dependencies | `pip-audit` and `npm audit`: no known vulnerabilities | Re-run before each release |

## Accepted risks and limits

- Rate limiting is in-process. With more than one API instance the limits apply per instance.
- The Supabase password used for development was pasted into a chat during setup; the project is a demo. Rotate it before any real deployment (Project Settings → Database).
- The dev database is shared by tests; tests roll back their own rows, but the project must not hold real passenger data.
- The MapTiler key is browser-visible by design; restrict it to the deployed origins in the provider dashboard.

## How to re-run

```bash
cd apps/api && .venv/Scripts/python -m pytest -q -m db tests/db/test_security_matrix.py
cd apps/api && .venv/Scripts/python -m pip_audit -r requirements.txt
cd apps/web && npm audit --omit=dev
gitleaks detect --source . --log-opts="--all" --redact
```
