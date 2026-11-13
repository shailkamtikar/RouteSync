"""Reroute evaluation hook. The decision logic is added in its own milestone."""

import psycopg


def after_position_update(conn: psycopg.Connection, journey) -> None:
    """Called after new positions were stored for a journey."""
    return None
