"""Copy condition management (Rule 5)."""
from lms.db import transaction
from lms.models import BusinessRuleError, CopyCondition
from lms.repository import log_event
from lms.services.transitions import CONDITIONS, active_bookings_on_copy, load_actor


def set_condition(copy_id: int, condition: str, librarian_id: int) -> list[dict]:
    """Rule 5: mark a copy DAMAGED / UNDER_REPAIR / LOST / REFERENCE_ONLY, or AVAILABLE again.

    An unavailable copy is never allocated or issued. If the copy becomes unavailable, returns
    its active bookings that have not ended (end_date >= TODAY) so the UI can warn the
    librarian, who decides whether to cancel them (assumption 7). Returns [] otherwise.
    """
    condition = str(condition)
    if condition not in CONDITIONS:
        raise BusinessRuleError(f"Unknown copy condition: {condition}.")
    with transaction() as conn:
        if load_actor(conn, librarian_id)["role"] != "LIBRARIAN":
            raise BusinessRuleError("Only librarians can change a copy's condition.")
        copy = conn.execute("SELECT copy_code, condition FROM copies WHERE id = ?", (copy_id,)).fetchone()
        if copy is None:
            raise BusinessRuleError(f"Copy #{copy_id} does not exist.")
        if copy["condition"] != condition:
            conn.execute("UPDATE copies SET condition = ? WHERE id = ?", (condition, copy_id))
            log_event(conn, None, "CONDITION_CHANGED", librarian_id,
                      f"Copy {copy['copy_code']}: {copy['condition']} -> {condition}")
        if condition == CopyCondition.AVAILABLE.value:
            return []
        return active_bookings_on_copy(conn, copy_id)
