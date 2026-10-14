"""Read-only query helpers plus the event logger. No business rules here.

Read helpers open and close their own connection and return dicts.
log_event writes on the caller's connection so it is part of the caller's transaction.
"""
from datetime import datetime

from lms.db import get_conn

_BOOKING_SELECT = """
    SELECT bk.id, bk.member_id, bk.book_id, bk.copy_id, bk.start_date, bk.end_date,
           bk.status, bk.note, bk.created_at, bk.updated_at,
           m.name AS member_name, m.member_type, b.title AS book_title, c.copy_code
    FROM bookings bk
    JOIN members m ON m.id = bk.member_id
    JOIN books b ON b.id = bk.book_id
    JOIN copies c ON c.id = bk.copy_id
"""


def _all(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _one(sql: str, params: tuple = ()) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_members() -> list[dict]:
    return _all("SELECT id, name, email, role, member_type FROM members ORDER BY id")


def get_member(member_id: int) -> dict | None:
    return _one("SELECT id, name, email, role, member_type FROM members WHERE id = ?", (member_id,))


def list_books() -> list[dict]:
    return _all(
        """
        SELECT b.id, b.title, b.author, b.category,
               (SELECT COUNT(*) FROM copies c WHERE c.book_id = b.id) AS total_copies
        FROM books b
        ORDER BY b.title
        """
    )


def list_copies(book_id: int | None = None) -> list[dict]:
    sql = """
        SELECT c.id, c.book_id, c.copy_code, c.condition, b.title AS book_title
        FROM copies c
        JOIN books b ON b.id = c.book_id
    """
    params: tuple = ()
    if book_id is not None:
        sql += " WHERE c.book_id = ?"
        params = (book_id,)
    return _all(sql + " ORDER BY c.id", params)


def list_bookings(member_id: int | None = None, status: str | None = None) -> list[dict]:
    clauses, params = [], []
    if member_id is not None:
        clauses.append("bk.member_id = ?")
        params.append(member_id)
    if status is not None:
        clauses.append("bk.status = ?")
        params.append(str(status))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return _all(_BOOKING_SELECT + where + " ORDER BY bk.created_at DESC, bk.id DESC", tuple(params))


def get_booking(booking_id: int) -> dict | None:
    return _one(_BOOKING_SELECT + " WHERE bk.id = ?", (booking_id,))


def list_events(limit: int = 20) -> list[dict]:
    """Newest first. actor_name is whoever performed the action; book_title is the booking's book."""
    return _all(
        """
        SELECT e.id, e.booking_id, e.action, e.actor_id, e.at, e.detail,
               m.name AS actor_name, b.title AS book_title
        FROM events e
        LEFT JOIN members m ON m.id = e.actor_id
        LEFT JOIN bookings bk ON bk.id = e.booking_id
        LEFT JOIN books b ON b.id = bk.book_id
        ORDER BY e.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def log_event(conn, booking_id: int | None, action: str, actor_id: int | None, detail: str = "") -> None:
    """Record an audit event on the caller's connection (no commit; the caller's transaction does it)."""
    conn.execute(
        "INSERT INTO events (booking_id, action, actor_id, at, detail) VALUES (?, ?, ?, ?, ?)",
        (booking_id, str(action), actor_id, datetime.now().isoformat(timespec="seconds"), detail),
    )
