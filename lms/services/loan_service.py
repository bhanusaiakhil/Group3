"""Issuing, returning and overdue loans (Rules 5, 6, 9)."""
from datetime import date

import config
from lms.db import get_conn, transaction
from lms.models import BookingStatus, BusinessRuleError, CopyCondition
from lms.services.transitions import (
    CONDITIONS, active_bookings_on_copy, check_transition, fmt_date, load_actor, load_booking, move,
    require_librarian,
)


def issue(booking_id: int, librarian_id: int) -> None:
    """Rule 6: only a reviewed (RESERVED) booking becomes a loan. Rule 5: copy must be AVAILABLE.

    Can only be picked up within the booked period (not before it starts, not after it ends),
    and only once the copy's previous borrower has returned it (Rule 3).
    """
    with transaction() as conn:
        booking = load_booking(conn, booking_id)
        require_librarian(load_actor(conn, librarian_id), "issue")
        check_transition(booking, "issue")
        if booking["copy_condition"] != CopyCondition.AVAILABLE.value:
            raise BusinessRuleError(
                f"Copy {booking['copy_code']} is {booking['copy_condition']} and cannot be issued. "
                "Cancel this booking so the member can request again."
            )
        if date.fromisoformat(booking["start_date"]) > config.TODAY:
            raise BusinessRuleError(
                f"Booking #{booking_id} starts on {fmt_date(booking['start_date'])}; it cannot be "
                f"issued before then (today is {fmt_date(config.TODAY)})."
            )
        if date.fromisoformat(booking["end_date"]) < config.TODAY:
            raise BusinessRuleError(
                f"Booking #{booking_id} ended on {fmt_date(booking['end_date'])} and was never collected, "
                "so it can no longer be issued. Cancel it to release the copy."
            )
        still_out = conn.execute(
            """
            SELECT m.name, bk.end_date FROM bookings bk JOIN members m ON m.id = bk.member_id
            WHERE bk.copy_id = ? AND bk.status = ? AND bk.id != ?
            """,
            (booking["copy_id"], BookingStatus.ISSUED.value, booking_id),
        ).fetchone()
        if still_out:
            raise BusinessRuleError(
                f"Copy {booking['copy_code']} is still on loan to {still_out['name']} (due "
                f"{fmt_date(still_out['end_date'])}) and has not been returned yet, so it cannot be issued."
            )
        move(conn, booking, "issue", librarian_id,
             detail=f"Copy {booking['copy_code']} due back {booking['end_date']}")


def return_book(booking_id: int, librarian_id: int,
                condition: str = CopyCondition.AVAILABLE.value) -> list[dict]:
    """Rule 9: ISSUED -> RETURNED. The copy is released unless it comes back unavailable.

    The copy's condition is set to `condition` (e.g. DAMAGED keeps it out of circulation).
    Returns other active bookings on that copy if it is now unavailable, so the UI can warn.
    """
    condition = str(condition)
    if condition not in CONDITIONS:
        raise BusinessRuleError(f"Unknown copy condition: {condition}.")
    with transaction() as conn:
        booking = load_booking(conn, booking_id)
        require_librarian(load_actor(conn, librarian_id), "return")
        check_transition(booking, "return")
        days_late = (config.TODAY - date.fromisoformat(booking["end_date"])).days
        late = f", {days_late} day(s) late" if days_late > 0 else ""
        move(conn, booking, "return", librarian_id,
             detail=f"Copy {booking['copy_code']} returned as {condition}{late}")
        conn.execute("UPDATE copies SET condition = ? WHERE id = ?", (condition, booking["copy_id"]))
        if condition == CopyCondition.AVAILABLE.value:
            return []
        return active_bookings_on_copy(conn, booking["copy_id"])


def list_overdue() -> list[dict]:
    """ISSUED loans whose end date has passed config.TODAY. Computed on the fly, never stored."""
    today = config.TODAY.isoformat()
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT bk.id, bk.member_id, m.name AS member_name, b.title AS book_title,
                   c.copy_code, bk.start_date, bk.end_date,
                   CAST(julianday(?) - julianday(bk.end_date) AS INTEGER) AS days_overdue
            FROM bookings bk
            JOIN members m ON m.id = bk.member_id
            JOIN books b ON b.id = bk.book_id
            JOIN copies c ON c.id = bk.copy_id
            WHERE bk.status = ? AND bk.end_date < ?
            ORDER BY bk.end_date, bk.id
            """,
            (today, BookingStatus.ISSUED.value, today),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

