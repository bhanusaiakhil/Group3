"""Shared vocabulary: booking statuses, copy conditions and the error shown to users."""
from enum import Enum


class _ValueStr(str, Enum):
    def __str__(self) -> str:  # f"{BookingStatus.PENDING}" -> "PENDING", not "BookingStatus.PENDING"
        return self.value


class BookingStatus(_ValueStr):
    PENDING = "PENDING"      # submitted, copy held, awaiting librarian review
    RESERVED = "RESERVED"    # approved, waiting to be collected
    ISSUED = "ISSUED"        # on loan
    RETURNED = "RETURNED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CopyCondition(_ValueStr):
    AVAILABLE = "AVAILABLE"
    DAMAGED = "DAMAGED"
    UNDER_REPAIR = "UNDER_REPAIR"
    LOST = "LOST"
    REFERENCE_ONLY = "REFERENCE_ONLY"


class MemberType(_ValueStr):
    STUDENT = "STUDENT"
    RESEARCHER = "RESEARCHER"
    PROFESSOR = "PROFESSOR"


# When requests compete for the same copy, the higher number wins (Professor > Researcher > Student).
MEMBER_PRIORITY = {
    MemberType.PROFESSOR.value: 3,
    MemberType.RESEARCHER.value: 2,
    MemberType.STUDENT.value: 1,
}


# Bookings in these statuses hold their copy for their date range.
ACTIVE_STATUSES = (
    BookingStatus.PENDING.value,
    BookingStatus.RESERVED.value,
    BookingStatus.ISSUED.value,
)


class BusinessRuleError(Exception):
    """A business rule was violated. str(error) is shown to the user as-is, so write a full sentence."""
