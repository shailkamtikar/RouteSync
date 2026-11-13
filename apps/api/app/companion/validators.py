"""Checks on what goes into and comes out of the model."""

import re
import uuid

import psycopg

MAX_QUESTION_CHARS = 500
MAX_HISTORY_TURNS = 6
MAX_TURN_CHARS = 1200

PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SAFE_REFUSAL = (
    "I can't share personal or booking details. For anything about a booking, "
    "please contact the operator."
)


def private_strings(conn: psycopg.Connection, journey_id: uuid.UUID) -> list[str]:
    """Names, references, seats and phones on this journey. Never leaves the backend."""
    rows = conn.execute(
        "select b.reference, b.contact_name, p.name, p.seat_number, p.phone "
        "from public.bookings b "
        "left join public.booking_passengers p on p.booking_id = b.id "
        "where b.journey_id = %s",
        (journey_id,),
    ).fetchall()
    found: set[str] = set()
    for row in rows:
        for value in row:
            if value and len(str(value).strip()) >= 3:
                found.add(str(value).strip())
                # Also each word of a name, so "Asha" alone is caught.
                for word in str(value).split():
                    if len(word) >= 4 and word.isalpha():
                        found.add(word)
    return sorted(found, key=len, reverse=True)


def leaks(text: str, private: list[str]) -> bool:
    lowered = text.lower()
    if any(item.lower() in lowered for item in private):
        return True
    return bool(PHONE_RE.search(text) or EMAIL_RE.search(text))


def clean_answer(text: str, private: list[str]) -> tuple[str, bool]:
    """Return (answer, was_replaced)."""
    if leaks(text, private):
        return SAFE_REFUSAL, True
    return text.strip(), False


def clean_history(history: list[dict]) -> list[dict]:
    """Keep only the last few short, well-formed turns."""
    turns = []
    for item in history[-MAX_HISTORY_TURNS:]:
        role = item.get("role")
        text = str(item.get("text", ""))[:MAX_TURN_CHARS].strip()
        if role in ("user", "assistant") and text:
            turns.append({"role": role, "text": text})
    return turns
