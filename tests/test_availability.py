"""Rules 2, 3, 5: availability is decided per copy, per (inclusive) date range."""
from datetime import date

import pytest

import config
from lms import repository
from lms.db import get_conn
from lms.models import BusinessRuleError, CopyCondition
from lms.services.availability import availability_summary, find_free_copy, overlaps
from lms.services.copy_service import set_condition
from lms.services.request_service import submit_request


def aug(d: int) -> date:
    return date(2026, 8, d)


def free_copy_code(book: int, start: date, end: date) -> str | None:
    conn = get_conn()
    try:
        cid = find_free_copy(conn, book, start, end)
    finally:
        conn.close()
    return None if cid is None else next(c["copy_code"] for c in repository.list_copies() if c["id"] == cid)


# --- Test list 1: overlap is inclusive -------------------------------------------------------

@pytest.mark.parametrize("start,end", [
    (aug(8), aug(10)),   # starts on the last day
    (aug(1), aug(4)),    # ends on the first day
    (aug(5), aug(6)),    # inside
    (aug(1), aug(20)),   # covers
])
def test_rule3_overlap_is_inclusive(start, end):
    assert overlaps(aug(4), aug(8), start, end)
    assert overlaps(start, end, aug(4), aug(8))


@pytest.mark.parametrize("start,end", [(aug(1), aug(3)), (aug(9), aug(12))])
def test_rule3_disjoint_ranges_do_not_overlap(start, end):
    assert not overlaps(aug(4), aug(8), start, end)
    assert not overlaps(start, end, aug(4), aug(8))


@pytest.mark.parametrize("start,end", [
    (aug(8), aug(10)),   # request starts on the reservation's last day
    (aug(1), aug(4)),    # request ends on the reservation's first day
])
def test_rule3_reserved_copy_skipped_on_boundary_day(book_id, start, end):
    ia = book_id("Introduction to Algorithms")  # IA-1 reserved 4-8 Aug
    assert free_copy_code(ia, start, end) != "IA-1"


@pytest.mark.parametrize("start,end", [(aug(9), aug(10)), (aug(1), aug(3))])
def test_rule3_reserved_copy_free_outside_its_dates(book_id, start, end):
    ia = book_id("Introduction to Algorithms")
    assert free_copy_code(ia, start, end) == "IA-1"        # lowest id wins when free


# --- Test list 4 + Rule 5: unavailable copies are never allocated ----------------------------

def test_rule5_damaged_copy_never_allocated(book_id, asha, ravi):
    dp = book_id("Design Patterns")
    first = submit_request(asha, dp, aug(5), aug(10))
    assert repository.get_booking(first)["copy_code"] == "DP-2"

    with pytest.raises(BusinessRuleError, match=r"No copy of Design Patterns.*1 damaged"):
        submit_request(ravi, dp, aug(7), aug(9))
    assert all(b["copy_code"] != "DP-1" for b in repository.list_bookings())


def test_rule5_reference_only_copies_never_allocated(book_id, copy_id, asha, librarian):
    for n in range(1, 6):
        set_condition(copy_id(f"DB-{n}"), CopyCondition.REFERENCE_ONLY, librarian)
    before = len(repository.list_bookings())

    with pytest.raises(BusinessRuleError, match=r"No copy of Database System Concepts.*5 reference-only"):
        submit_request(asha, book_id("Database System Concepts"), aug(5), aug(6))
    assert len(repository.list_bookings()) == before


def test_rule5_restored_copy_is_allocatable_again(book_id, copy_id, librarian):
    dp = book_id("Design Patterns")
    set_condition(copy_id("DP-1"), CopyCondition.AVAILABLE, librarian)
    assert free_copy_code(dp, aug(5), aug(6)) == "DP-1"


# --- Rule 2: summary per title ------------------------------------------------------------

def test_rule2_availability_summary_counts():
    summary = {s["title"]: s for s in availability_summary(aug(5), aug(7))}
    counts = lambda t: (summary[t]["total"], summary[t]["unavailable"], summary[t]["committed"], summary[t]["free"])

    assert counts("Clean Code") == (4, 0, 0, 4)                                   # loans end 4 Aug
    assert counts("Introduction to Algorithms") == (3, 0, 1, 2)                   # IA-1 reserved 4-8
    assert counts("Design Patterns") == (2, 1, 0, 1)                              # DP-1 damaged
    assert counts("Database System Concepts") == (5, 0, 0, 5)
    assert counts("Artificial Intelligence: A Modern Approach") == (3, 0, 1, 2)   # AI-2 reserved 6-7
    for s in summary.values():
        assert s["total"] == s["unavailable"] + s["committed"] + s["free"]


# --- Assumption: an overdue loan blocks its copy until actually returned ---------------------

def test_rule2_overdue_loan_blocks_copy_until_returned(book_id, monkeypatch):
    cc = book_id("Clean Code")
    assert free_copy_code(cc, aug(5), aug(7)) == "CC-1"       # 1 Aug: loan ends 4 Aug, future is free

    monkeypatch.setattr(config, "TODAY", aug(10))             # CC-1, CC-2 now overdue, not returned
    assert free_copy_code(cc, aug(10), aug(12)) == "CC-3"
    summary = next(s for s in availability_summary(aug(10), aug(12)) if s["title"] == "Clean Code")
    assert (summary["committed"], summary["free"]) == (2, 2)
