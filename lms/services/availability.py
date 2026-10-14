"""Copy availability for a date range (Rules 2, 3, 5).

Dates are inclusive: a booking 4-8 Aug overlaps one that starts on 8 Aug.
A copy is free for [start, end] when its condition is AVAILABLE and no active
(PENDING / RESERVED / ISSUED) booking on it overlaps the range.
An overdue loan (ISSUED, end_date < TODAY) blocks its copy until it is actually returned,
because the book is not on the shelf.
"""
from datetime import date

import config
from lms.db import get_conn
from lms.models import ACTIVE_STATUSES, MEMBER_PRIORITY, BookingStatus, CopyCondition

_ACTIVE_IN = ", ".join("?" * len(ACTIVE_STATUSES))

# Active booking `bk` overlaps the requested range. Same formula as overlaps(), with the booking
# as (s1, e1) and the request as (s2, e2), except an overdue loan has no end yet.
# Parameters: see _range_params().
_ACTIVE_AND_OVERLAPPING = f"""
    bk.status IN ({_ACTIVE_IN})
    AND bk.start_date <= ?
    AND (? <= bk.end_date OR (bk.status = ? AND bk.end_date < ?))
"""

_OVERLAPPING_BOOKING = f"SELECT 1 FROM bookings bk WHERE bk.copy_id = c.id AND {_ACTIVE_AND_OVERLAPPING}"

_CONDITION_LABELS = {
    CopyCondition.DAMAGED.value: "damaged",
    CopyCondition.UNDER_REPAIR.value: "under repair",
    CopyCondition.LOST.value: "lost",
    CopyCondition.REFERENCE_ONLY.value: "reference-only",
}


def overlaps(s1: date, e1: date, s2: date, e2: date) -> bool:
    """True if the inclusive ranges [s1, e1] and [s2, e2] share at least one day."""
    return s1 <= e2 and s2 <= e1


def _range_params(start: date, end: date) -> tuple:
    """Parameters for _ACTIVE_AND_OVERLAPPING; reads config.TODAY at call time."""
    return (*ACTIVE_STATUSES, end.isoformat(), start.isoformat(),
            BookingStatus.ISSUED.value, config.TODAY.isoformat())


def find_free_copy(conn, book_id: int, start: date, end: date) -> int | None:
    """Lowest-id copy of the book that is AVAILABLE and not booked during [start, end]."""
    row = conn.execute(
        f"""
        SELECT c.id FROM copies c
        WHERE c.book_id = ? AND c.condition = ?
          AND NOT EXISTS ({_OVERLAPPING_BOOKING})
        ORDER BY c.id
        LIMIT 1
        """,
        (book_id, CopyCondition.AVAILABLE.value, *_range_params(start, end)),
    ).fetchone()
    return row["id"] if row else None


def find_displaceable_copy(conn, book_id: int, start: date, end: date,
                           priority: int) -> tuple[int, list[int]] | None:
    """Priority rule: an AVAILABLE copy whose only overlapping commitments are PENDING requests
    from members with lower priority than `priority`.

    Returns (copy_id, ids of the PENDING bookings to displace), preferring the copy that
    displaces the fewest requests, then the lowest id. Confirmed reservations (RESERVED) and
    loans (ISSUED) are never displaced. Only call this when find_free_copy found nothing.
    """
    rows = conn.execute(
        f"""
        SELECT c.id AS copy_id, bk.id AS booking_id, bk.status, m.member_type
        FROM copies c
        JOIN bookings bk ON bk.copy_id = c.id
        JOIN members m ON m.id = bk.member_id
        WHERE c.book_id = ? AND c.condition = ? AND {_ACTIVE_AND_OVERLAPPING}
        ORDER BY c.id, bk.id
        """,
        (book_id, CopyCondition.AVAILABLE.value, *_range_params(start, end)),
    ).fetchall()
    by_copy: dict[int, list] = {}
    for r in rows:
        by_copy.setdefault(r["copy_id"], []).append(r)
    candidates = [
        (len(blocking), copy_id, [b["booking_id"] for b in blocking])
        for copy_id, blocking in by_copy.items()
        if all(b["status"] == BookingStatus.PENDING.value
               and MEMBER_PRIORITY.get(b["member_type"], 0) < priority for b in blocking)
    ]
    if not candidates:
        return None
    _, copy_id, booking_ids = min(candidates)
    return copy_id, booking_ids


def unavailable_reasons(conn, book_id: int, start: date, end: date) -> list[str]:
    """Why copies of a book are not free, e.g. ["1 damaged", "1 already booked"]."""
    rows = conn.execute(
        f"""
        SELECT CASE
                 WHEN c.condition != ? THEN c.condition
                 WHEN EXISTS ({_OVERLAPPING_BOOKING}) THEN 'BOOKED'
               END AS reason,
               COUNT(*) AS n
        FROM copies c
        WHERE c.book_id = ?
        GROUP BY reason
        HAVING reason IS NOT NULL
        ORDER BY reason = 'BOOKED', reason
        """,
        (CopyCondition.AVAILABLE.value, *_range_params(start, end), book_id),
    ).fetchall()
    return [
        f"{r['n']} {'already booked' if r['reason'] == 'BOOKED' else _CONDITION_LABELS[r['reason']]}"
        for r in rows
    ]


def availability_summary(start: date, end: date) -> list[dict]:
    """Per title for [start, end]: total, unavailable (condition), committed (booked), free."""
    conn = get_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT b.id AS book_id, b.title, b.author, b.category,
                   COUNT(c.id) AS total,
                   COALESCE(SUM(c.condition != ?), 0) AS unavailable,
                   COALESCE(SUM(c.condition = ? AND EXISTS ({_OVERLAPPING_BOOKING})), 0) AS committed
            FROM books b
            LEFT JOIN copies c ON c.book_id = b.id
            GROUP BY b.id
            ORDER BY b.title
            """,
            (CopyCondition.AVAILABLE.value, CopyCondition.AVAILABLE.value, *_range_params(start, end)),
        ).fetchall()
    finally:
        conn.close()
    summary = [dict(r) for r in rows]
    for s in summary:
        s["free"] = s["total"] - s["unavailable"] - s["committed"]
    return summary
