"""Submitting a borrowing request: Rules 1, 3, 4, 10 and the documented validations."""
import threading
from datetime import date

import pytest

import config
from lms import repository
from lms.models import BusinessRuleError
from lms.services.request_service import submit_request


def aug(d: int) -> date:
    return date(2026, 8, d)


def booking_count() -> int:
    return len(repository.list_bookings())


# --- Test list 2: a valid request becomes PENDING and holds a copy ---------------------------

def test_rule1_submit_creates_pending_booking_with_copy(asha, book_id):
    bid = submit_request(asha, book_id("Database System Concepts"), aug(5), aug(10))

    b = repository.get_booking(bid)
    assert b["status"] == "PENDING"
    assert b["member_id"] == asha and b["book_title"] == "Database System Concepts"
    assert b["copy_code"].startswith("DB-")
    assert (b["start_date"], b["end_date"]) == ("2026-08-05", "2026-08-10")
    assert repository.list_events(1)[0]["action"] == "SUBMITTED"


# --- Test list 3 + Rule 4: blocked when every copy is committed ------------------------------

def test_rule4_submit_blocked_when_all_copies_committed(asha, ravi, book_id):
    cc = book_id("Clean Code")                       # CC-1, CC-2 issued until 4 Aug
    assert repository.get_booking(submit_request(asha, cc, aug(1), aug(4)))["copy_code"] == "CC-3"
    assert repository.get_booking(submit_request(ravi, cc, aug(2), aug(3)))["copy_code"] == "CC-4"
    before = booking_count()

    with pytest.raises(BusinessRuleError, match=r"No copy of Clean Code is available from 03 Aug to 04 Aug"):
        submit_request(asha, cc, aug(3), aug(4))
    assert booking_count() == before


def test_rule10_no_copy_message_gives_reason(asha, ravi, book_id):
    dp = book_id("Design Patterns")
    submit_request(asha, dp, aug(5), aug(10))

    with pytest.raises(BusinessRuleError) as err:
        submit_request(ravi, dp, aug(7), aug(9))
    assert str(err.value) == (
        "No copy of Design Patterns is available from 07 Aug to 09 Aug (1 damaged, 1 already booked)."
    )


# --- Extra: competing for the last free copy -------------------------------------------------

@pytest.mark.parametrize("start,end", [(aug(10), aug(12)), (aug(1), aug(5))])  # share only 10 Aug / 5 Aug
def test_rule3_second_request_for_last_free_copy_fails(asha, ravi, book_id, start, end):
    dp = book_id("Design Patterns")                  # only DP-2 is usable
    submit_request(asha, dp, aug(5), aug(10))

    with pytest.raises(BusinessRuleError, match="No copy of Design Patterns"):
        submit_request(ravi, dp, start, end)
    dp2 = [b for b in repository.list_bookings() if b["copy_code"] == "DP-2"]
    assert len(dp2) == 1 and dp2[0]["member_id"] == asha


def test_rule3_simultaneous_requests_for_last_copy_only_one_wins(asha, ravi, book_id):
    dp = book_id("Design Patterns")
    barrier = threading.Barrier(2)
    results = {}

    def attempt(member):
        barrier.wait()
        try:
            results[member] = submit_request(member, dp, aug(5), aug(6))
        except BusinessRuleError as e:
            results[member] = e

    threads = [threading.Thread(target=attempt, args=(m,)) for m in (asha, ravi)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    winners = [r for r in results.values() if isinstance(r, int)]
    losers = [r for r in results.values() if isinstance(r, BusinessRuleError)]
    assert len(winners) == 1 and len(losers) == 1
    assert len([b for b in repository.list_bookings() if b["copy_code"] == "DP-2"]) == 1


# --- Test list 8: validations -----------------------------------------------------------------

@pytest.mark.parametrize("start,end,message", [
    (date(2026, 7, 31), aug(3), "cannot be before today"),
    (aug(9), aug(6), "on or after the start date"),
    (aug(1), aug(15), "at most 14 days"),
])
def test_validation_invalid_dates_rejected(asha, book_id, start, end, message):
    before = booking_count()
    with pytest.raises(BusinessRuleError, match=message):
        submit_request(asha, book_id("Database System Concepts"), start, end)
    assert booking_count() == before


def test_validation_exactly_max_loan_days_allowed(asha, book_id):
    bid = submit_request(asha, book_id("Database System Concepts"), aug(1), aug(14))  # 14 days inclusive
    assert repository.get_booking(bid)["status"] == "PENDING"


def test_validation_same_day_loan_allowed(asha, book_id):
    bid = submit_request(asha, book_id("Database System Concepts"), aug(5), aug(5))
    assert repository.get_booking(bid)["status"] == "PENDING"


def test_validation_max_active_bookings(meera, book_id):
    assert len([b for b in repository.list_bookings(member_id=meera)
                if b["status"] in ("PENDING", "RESERVED", "ISSUED")]) == config.MAX_ACTIVE
    before = booking_count()

    with pytest.raises(BusinessRuleError, match=f"{config.MAX_ACTIVE} active bookings"):
        submit_request(meera, book_id("Database System Concepts"), aug(5), aug(6))
    assert booking_count() == before


def test_validation_start_date_uses_current_system_date(asha, book_id, monkeypatch):
    monkeypatch.setattr(config, "TODAY", aug(10))
    with pytest.raises(BusinessRuleError, match="cannot be before today"):
        submit_request(asha, book_id("Database System Concepts"), aug(9), aug(11))


def test_rule1_librarian_cannot_submit_request(librarian, book_id):
    with pytest.raises(BusinessRuleError, match="Only library members"):
        submit_request(librarian, book_id("Database System Concepts"), aug(5), aug(6))


@pytest.mark.parametrize("bad", ["member", "book"])
def test_rule1_unknown_member_or_book_rejected(asha, book_id, bad):
    member, book = (999, book_id("Clean Code")) if bad == "member" else (asha, 999)
    before = booking_count()
    with pytest.raises(BusinessRuleError, match="does not exist"):
        submit_request(member, book, aug(5), aug(6))
    assert booking_count() == before
