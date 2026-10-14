"""Booking state machine and helpers shared by the review, loan and copy services (Rules 5-9).

ALLOWED is the single source of truth: any (status, action) pair not listed is refused.
Closed statuses (REJECTED, CANCELLED, RETURNED) appear in no "from" set, so they are final.
"""
from datetime import date, datetime

import config
from lms.models import ACTIVE_STATUSES, BookingStatus as S, BusinessRuleError, CopyCondition
from lms.repository import log_event

ALLOWED = {
    "approve": {"from": {S.PENDING.value}, "to": S.RESERVED.value, "verb": "approved"},
    "reject": {"from": {S.PENDING.value}, "to": S.REJECTED.value, "verb": "rejected"},
    "cancel": {"from": {S.PENDING.value, S.RESERVED.value}, "to": S.CANCELLED.value, "verb": "cancelled"},
    "issue": {"from": {S.RESERVED.value}, "to": S.ISSUED.value, "verb": "issued"},
    "return": {"from": {S.ISSUED.value}, "to": S.RETURNED.value, "verb": "returned"},
}

CONDITIONS = {c.value for c in CopyCondition}


def fmt_date(iso: str | date) -> str:
    d = date.fromisoformat(iso) if isinstance(iso, str) else iso
    return d.strftime("%d %b")  # 07 Aug


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_booking(conn, booking_id: int):
    """Booking row plus its copy's code and condition; raises if missing."""
    row = conn.execute(
        """
        SELECT bk.*, c.copy_code, c.condition AS copy_condition
        FROM bookings bk JOIN copies c ON c.id = bk.copy_id
        WHERE bk.id = ?
        """,
        (booking_id,),
    ).fetchone()
    if row is None:
        raise BusinessRuleError(f"Booking #{booking_id} does not exist.")
    return row


def load_actor(conn, actor_id: int):
    row = conn.execute("SELECT id, name, role FROM members WHERE id = ?", (actor_id,)).fetchone()
    if row is None:
        raise BusinessRuleError("The selected user does not exist.")
    return row


def require_librarian(actor, action: str) -> None:
    if actor["role"] != "LIBRARIAN":
        raise BusinessRuleError(f"Only librarians can {action} bookings.")


def check_transition(booking, action: str) -> None:
    """Raise unless ALLOWED permits `action` from the booking's current status."""
    rule = ALLOWED[action]
    if booking["status"] not in rule["from"]:
        allowed = " or ".join(sorted(rule["from"]))
        raise BusinessRuleError(
            f"Booking #{booking['id']} is {booking['status']}; "
            f"only {allowed} bookings can be {rule['verb']}."
        )


def move(conn, booking, action: str, actor_id: int, note: str | None = None, detail: str = "") -> None:
    """Apply the transition: UPDATE status (+ note) and updated_at, then log the event."""
    new_status = ALLOWED[action]["to"]
    conn.execute(
        "UPDATE bookings SET status = ?, note = COALESCE(?, note), updated_at = ? WHERE id = ?",
        (new_status, note, now_iso(), booking["id"]),
    )
    log_event(conn, booking["id"], new_status, actor_id, detail)


def active_bookings_on_copy(conn, copy_id: int) -> list[dict]:
    """Active bookings on a copy that have not ended yet (end_date >= config.TODAY)."""
    rows = conn.execute(
        f"""
        SELECT bk.id, bk.status, bk.start_date, bk.end_date, m.name AS member_name
        FROM bookings bk JOIN members m ON m.id = bk.member_id
        WHERE bk.copy_id = ? AND bk.status IN ({', '.join('?' * len(ACTIVE_STATUSES))})
          AND bk.end_date >= ?
        ORDER BY bk.start_date
        """,
        (copy_id, *ACTIVE_STATUSES, config.TODAY.isoformat()),
    ).fetchall()
    return [dict(r) for r in rows]
