"""Librarian review and cancellation (Rules 6, 7, 8)."""
from lms.db import transaction
from lms.models import BusinessRuleError, CopyCondition
from lms.services.transitions import check_transition, load_actor, load_booking, move, require_librarian


def approve(booking_id: int, librarian_id: int) -> None:
    """Rule 6: PENDING -> RESERVED after librarian review. Rule 5: the copy must still be AVAILABLE."""
    with transaction() as conn:
        booking = load_booking(conn, booking_id)
        require_librarian(load_actor(conn, librarian_id), "approve")
        check_transition(booking, "approve")
        if booking["copy_condition"] != CopyCondition.AVAILABLE.value:
            raise BusinessRuleError(
                f"Copy {booking['copy_code']} is now {booking['copy_condition']}, so booking "
                f"#{booking_id} cannot be approved. Reject it with a reason instead."
            )
        move(conn, booking, "approve", librarian_id, detail=f"Copy {booking['copy_code']} reserved")


def reject(booking_id: int, librarian_id: int, reason: str) -> None:
    """Rules 6, 7: PENDING -> REJECTED with a reason. The booking is closed, which releases its copy."""
    with transaction() as conn:
        booking = load_booking(conn, booking_id)
        require_librarian(load_actor(conn, librarian_id), "reject")
        check_transition(booking, "reject")
        reason = (reason or "").strip()
        if not reason:
            raise BusinessRuleError("Please give a reason for rejecting this booking.")
        move(conn, booking, "reject", librarian_id, note=reason, detail=reason)


def cancel(booking_id: int, actor_id: int, reason: str = "") -> None:
    """Rule 8: PENDING/RESERVED -> CANCELLED before issue, which releases the copy.

    A member may cancel only their own booking; a librarian may cancel any.
    """
    with transaction() as conn:
        booking = load_booking(conn, booking_id)
        actor = load_actor(conn, actor_id)
        if actor["role"] != "LIBRARIAN" and booking["member_id"] != actor_id:
            raise BusinessRuleError("You can only cancel your own bookings.")
        check_transition(booking, "cancel")
        reason = (reason or "").strip()
        move(conn, booking, "cancel", actor_id, note=reason or None,
             detail=reason or f"Cancelled by {actor['name']}")
