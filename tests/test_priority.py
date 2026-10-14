"""Member types: loan length limits per type, and priority Professor > Researcher > Student
when requests compete for the same copy."""
from datetime import date, timedelta

import pytest

import config
from lms import repository
from lms.models import BusinessRuleError
from lms.services.request_service import submit_request
from lms.services.review_service import approve, cancel


def aug(d: int) -> date:
    return date(2026, 8, d)


def status(booking_id: int) -> str:
    return repository.get_booking(booking_id)["status"]


@pytest.fixture
def researcher(meera, seeded_booking):
    """Meera (researcher) with one booking freed, so she is below the active-booking limit."""
    cancel(seeded_booking(meera, "Introduction to Algorithms")["id"], meera)
    return meera


# --- Loan length limit depends on member type ------------------------------------------------

@pytest.mark.parametrize("who,member_type", [("asha", "STUDENT"), ("researcher", "RESEARCHER"),
                                            ("professor", "PROFESSOR")])
def test_loan_limit_depends_on_member_type(request, book_id, who, member_type):
    member = request.getfixturevalue(who)
    assert repository.get_member(member)["member_type"] == member_type
    limit = config.MAX_LOAN_DAYS_BY_TYPE[member_type]
    db = book_id("Database System Concepts")
    before = len(repository.list_bookings())

    with pytest.raises(BusinessRuleError, match=f"at most {limit} days; you asked for {limit + 1} days"):
        submit_request(member, db, aug(1), aug(1) + timedelta(days=limit))        # limit + 1 days
    assert len(repository.list_bookings()) == before

    bid = submit_request(member, db, aug(1), aug(1) + timedelta(days=limit - 1))  # exactly the limit
    assert status(bid) == "PENDING"


def test_limits_increase_with_seniority():
    limits = config.MAX_LOAN_DAYS_BY_TYPE
    assert limits["STUDENT"] < limits["RESEARCHER"] < limits["PROFESSOR"]


# --- Priority: higher type takes a copy held only by lower-priority PENDING requests ------------

def test_priority_professor_displaces_pending_student_request(asha, professor, book_id):
    dp = book_id("Design Patterns")                      # only DP-2 is usable
    student = submit_request(asha, dp, aug(5), aug(10))

    prof = submit_request(professor, dp, aug(7), aug(9))

    assert repository.get_booking(prof)["copy_code"] == "DP-2" and status(prof) == "PENDING"
    bumped = repository.get_booking(student)
    assert bumped["status"] == "REJECTED"                # closed, so the copy is released (Rule 7)
    assert "higher priority" in bumped["note"]
    event = next(e for e in repository.list_events(5) if e["booking_id"] == student)
    assert event["action"] == "REJECTED" and event["actor_name"] is None and "Anil Mehta" in event["detail"]


def test_priority_researcher_displaces_student(asha, researcher, book_id):
    dp = book_id("Design Patterns")
    student = submit_request(asha, dp, aug(5), aug(10))
    res = submit_request(researcher, dp, aug(6), aug(8))
    assert repository.get_booking(res)["copy_code"] == "DP-2"
    assert status(student) == "REJECTED"


def test_priority_professor_displaces_researcher(researcher, professor, book_id):
    dp = book_id("Design Patterns")
    res = submit_request(researcher, dp, aug(5), aug(10))
    submit_request(professor, dp, aug(5), aug(6))
    assert status(res) == "REJECTED"


def test_priority_lower_type_cannot_displace_higher(asha, professor, book_id):
    dp = book_id("Design Patterns")
    prof = submit_request(professor, dp, aug(5), aug(10))
    before = len(repository.list_bookings())

    with pytest.raises(BusinessRuleError, match=r"No copy of Design Patterns.*1 already booked"):
        submit_request(asha, dp, aug(7), aug(9))
    assert status(prof) == "PENDING" and len(repository.list_bookings()) == before


def test_priority_equal_types_first_come_first_served(asha, ravi, book_id):
    dp = book_id("Design Patterns")                      # Asha and Ravi are both students
    first = submit_request(asha, dp, aug(5), aug(10))
    with pytest.raises(BusinessRuleError, match="No copy of Design Patterns"):
        submit_request(ravi, dp, aug(7), aug(9))
    assert status(first) == "PENDING"


def test_priority_never_displaces_confirmed_reservation(asha, professor, librarian, book_id):
    dp = book_id("Design Patterns")
    student = submit_request(asha, dp, aug(5), aug(10))
    approve(student, librarian)                          # now a confirmed reservation

    with pytest.raises(BusinessRuleError, match="No copy of Design Patterns"):
        submit_request(professor, dp, aug(7), aug(9))
    assert status(student) == "RESERVED"


def test_priority_never_displaces_loan(meera, professor, book_id):
    # CC-1 and CC-2 are on loan until 4 Aug; the professor takes the free CC-3 and CC-4 first.
    cc = book_id("Clean Code")
    loans_before = [b["id"] for b in repository.list_bookings(status="ISSUED")]
    submit_request(professor, cc, aug(1), aug(4))        # CC-3 is free: no displacement needed
    submit_request(professor, cc, aug(2), aug(3))        # CC-4 is free
    with pytest.raises(BusinessRuleError, match="No copy of Clean Code"):
        submit_request(professor, cc, aug(3), aug(4))    # only loans left: never displaced
    assert all(status(b) == "ISSUED" for b in loans_before)


def test_priority_prefers_free_copy_over_displacing(asha, professor, book_id):
    db = book_id("Database System Concepts")             # 5 copies
    student = submit_request(asha, db, aug(5), aug(6))   # takes DB-1
    prof = submit_request(professor, db, aug(5), aug(6))
    assert repository.get_booking(prof)["copy_code"] == "DB-2"
    assert status(student) == "PENDING"


def test_priority_displaces_every_overlapping_lower_request_on_the_copy(asha, ravi, professor, book_id):
    dp = book_id("Design Patterns")
    first = submit_request(asha, dp, aug(5), aug(6))     # both students hold DP-2 on different days
    second = submit_request(ravi, dp, aug(8), aug(9))
    prof = submit_request(professor, dp, aug(5), aug(9))
    assert repository.get_booking(prof)["copy_code"] == "DP-2"
    assert status(first) == status(second) == "REJECTED"


def test_displaced_student_can_request_other_dates(asha, professor, book_id):
    dp = book_id("Design Patterns")
    submit_request(asha, dp, aug(5), aug(10))
    submit_request(professor, dp, aug(5), aug(10))
    again = submit_request(asha, dp, aug(11), aug(14))   # Rule 7: a new request with revised dates
    assert status(again) == "PENDING"
