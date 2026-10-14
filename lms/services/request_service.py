"""Submitting a borrowing request (Rules 1-4, 10, member-type limits and priority)."""
from datetime import date, datetime

import config
from lms.db import transaction
from lms.models import ACTIVE_STATUSES, MEMBER_PRIORITY, BookingStatus, BusinessRuleError
from lms.repository import log_event
from lms.services.availability import find_displaceable_copy, find_free_copy, unavailable_reasons
from lms.services.transitions import check_transition, load_booking, move


def _fmt(d: date) -> str:
    return d.strftime("%d %b")  # 07 Aug


def submit_request(member_id: int, book_id: int, start: date, end: date) -> int:
    """Create a PENDING booking holding a copy and return its id.

    If no copy is free, a higher-priority member (Professor > Researcher > Student) may take a
    copy held only by lower-priority PENDING requests; those requests are closed as REJECTED
    with the reason, which releases the copy (Rule 7).
    Raises BusinessRuleError with a user-facing sentence if any rule fails.
    Every check and the INSERT run in one transaction, so two requests can never take the same copy.
    """
    today = config.TODAY
    with transaction() as conn:
        # Rule 1: the request belongs to an existing library member...
        member = conn.execute("SELECT name, role, member_type FROM members WHERE id = ?", (member_id,)).fetchone()
        if member is None:
            raise BusinessRuleError("This member does not exist.")
        if member["role"] != "MEMBER":
            raise BusinessRuleError(
                f"Only library members can submit borrowing requests; {member['name']} is a librarian."
            )

        # Rule 1: ...for an existing book title...
        book = conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
        if book is None:
            raise BusinessRuleError("This book does not exist in the catalogue.")

        # Rule 1: ...with a start date and an expected return date (assumption 4: valid dates).
        if start is None or end is None:
            raise BusinessRuleError("Please choose both a start date and a return date.")
        if start < today:
            raise BusinessRuleError(
                f"The start date ({_fmt(start)}) cannot be before today ({_fmt(today)})."
            )
        if end < start:
            raise BusinessRuleError(
                f"The return date ({_fmt(end)}) must be on or after the start date ({_fmt(start)})."
            )

        # Assumption 4: loan length limit depends on the member type (dates inclusive, so 1-14 Aug
        # is 14 days).
        member_type = member["member_type"]
        max_days = config.MAX_LOAN_DAYS_BY_TYPE[member_type]
        days = (end - start).days + 1
        if days > max_days:
            raise BusinessRuleError(
                f"As a {member_type.lower()} you can borrow a book for at most {max_days} days; "
                f"you asked for {days} days."
            )

        # Assumption 4: limit on active bookings per member.
        active = conn.execute(
            f"SELECT COUNT(*) FROM bookings WHERE member_id = ? AND status IN ({', '.join('?' * len(ACTIVE_STATUSES))})",
            (member_id, *ACTIVE_STATUSES),
        ).fetchone()[0]
        if active >= config.MAX_ACTIVE:
            raise BusinessRuleError(
                f"You already have {active} active bookings (the limit is {config.MAX_ACTIVE}). "
                "Cancel or return one before requesting another."
            )

        # Rules 2, 3, 5: prefer a copy that is free for the whole period.
        copy_id, displaced = find_free_copy(conn, book_id, start, end), []
        # Priority rule: otherwise take a copy held only by lower-priority PENDING requests.
        if copy_id is None:
            copy_id, displaced = find_displaceable_copy(
                conn, book_id, start, end, MEMBER_PRIORITY[member_type]) or (None, [])
        # Rules 4, 10: block the request, with the reason, if no copy can be committed.
        if copy_id is None:
            reasons = unavailable_reasons(conn, book_id, start, end)
            detail = f" ({', '.join(reasons)})" if reasons else " (the library holds no copies)"
            raise BusinessRuleError(
                f"No copy of {book['title']} is available from {_fmt(start)} to {_fmt(end)}{detail}."
            )

        # Rule 7: displaced requests are closed (REJECTED) with the reason, which releases the copy.
        for displaced_id in displaced:
            other = load_booking(conn, displaced_id)
            check_transition(other, "reject")
            reason = (f"The copy was given to a {member_type.lower()}'s request for overlapping dates "
                      "(higher priority)")
            move(conn, other, "reject", None, note=reason,
                 detail=f"Copy given to {member['name']} ({member_type.title()}, higher priority)")

        # Rules 3, 6: commit the copy now as PENDING; it waits for librarian review.
        now = datetime.now().isoformat(timespec="seconds")
        booking_id = conn.execute(
            "INSERT INTO bookings (member_id, book_id, copy_id, start_date, end_date, status,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (member_id, book_id, copy_id, start.isoformat(), end.isoformat(),
             BookingStatus.PENDING.value, now, now),
        ).lastrowid
        copy_code = conn.execute("SELECT copy_code FROM copies WHERE id = ?", (copy_id,)).fetchone()[0]
        log_event(conn, booking_id, "SUBMITTED", member_id,
                  f"Copy {copy_code}, {start.isoformat()} to {end.isoformat()}")
    return booking_id
