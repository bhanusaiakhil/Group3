"""Member pages: home, browse books (with request dialog), my bookings.

Presentation only: every rule lives in the services; these pages show their results and errors.
"""
from datetime import timedelta

import streamlit as st

import config
from lms import repository
from lms.models import BookingStatus, BusinessRuleError
from lms.services.availability import availability_summary
from lms.services.loan_service import list_overdue
from lms.services.request_service import submit_request
from lms.services.review_service import cancel
from ui import components as ui

CANCELLABLE = {BookingStatus.PENDING.value, BookingStatus.RESERVED.value}
OPEN = CANCELLABLE | {BookingStatus.ISSUED.value}


def _max_days(user: dict) -> int:
    return config.MAX_LOAN_DAYS_BY_TYPE[user["member_type"]]


def _my_overdue_ids(user: dict) -> set[int]:
    return {o["id"] for o in list_overdue() if o["member_id"] == user["id"]}


# --- Home -------------------------------------------------------------------------------------

def home(user: dict) -> None:
    ui.hero(f"Welcome back, {user['name'].split()[0]}",
            "Find a book, see when a copy is free, and request it in seconds. "
            "A librarian reviews every request.",
            eyebrow=f"Campus Library · {ui.type_label(user['member_type'])} account")
    bookings = repository.list_bookings(member_id=user["id"])
    overdue = _my_overdue_ids(user)
    count = lambda s: sum(b["status"] == s for b in bookings)

    cols = st.columns(4)
    cols[0].metric("Pending review", count(BookingStatus.PENDING.value), border=True)
    cols[1].metric("Ready to collect", count(BookingStatus.RESERVED.value), border=True)
    cols[2].metric("On loan", count(BookingStatus.ISSUED.value), border=True)
    cols[3].metric("Overdue", len(overdue), border=True)
    if overdue:
        st.warning(f"You have {len(overdue)} overdue book(s). Please return them to the library desk.", icon="⚠️")

    left, right = st.columns([3, 2], gap="large")
    with left:
        ui.section("Coming up", "Your pending requests, reservations and loans.")
        upcoming = sorted((b for b in bookings if b["status"] in OPEN), key=lambda b: b["start_date"])
        if not upcoming:
            st.info("Nothing booked yet – browse the catalogue to borrow your first book.")
        for b in upcoming[:4]:
            _booking_row(b, overdue=b["id"] in overdue)
    with right:
        ui.section("Quick links")
        with st.container(border=True):
            ui.nav_link("books", "Browse books and check availability", "🔎")
            ui.nav_link("my-bookings", "Manage my bookings", "🗓️")
        with st.container(border=True):
            st.markdown("**Your borrowing rights**")
            ui.type_badge(user["member_type"])
            st.caption(f"Loans of up to {_max_days(user)} days · up to {config.MAX_ACTIVE} active bookings. "
                       "When requests clash, priority goes Professor > Researcher > Student "
                       "(confirmed reservations are never taken away).")


# --- Browse -----------------------------------------------------------------------------------

def browse(user: dict) -> None:
    ui.section("Browse books", "Pick your dates to see how many copies are free for that period.")
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([2.2, 1.6, 1.2, 1.2])
        query = c1.text_input("Search", placeholder="Title or author", key="browse_query")
        categories = sorted({b["category"] for b in repository.list_books() if b["category"]})
        category = c2.selectbox("Category", ["All categories", *categories], key="browse_category")
        start = c3.date_input("From", value=config.TODAY, key="browse_start", format="DD/MM/YYYY")
        end = c4.date_input("To", value=config.TODAY + timedelta(days=7), key="browse_end", format="DD/MM/YYYY")
    if end < start:
        st.warning("'To' must be on or after 'From'.")
        return

    books = [
        b for b in availability_summary(start, end)
        if (category == "All categories" or b["category"] == category)
        and query.lower() in f"{b['title']} {b['author'] or ''}".lower()
    ]
    st.caption(f"{len(books)} title(s) · availability for {ui.fmt(start)} – {ui.fmt(end)}")
    if not books:
        st.info("No books match your search.")
    for row_start in range(0, len(books), 3):
        cols = st.columns(3)
        for col, book in zip(cols, books[row_start:row_start + 3]):
            with col.container(border=True):
                _book_card(user, book, start, end)


def _book_card(user: dict, book: dict, start, end) -> None:
    ui.cover(book["title"], book["category"])
    ui.book_heading(book["title"], book["author"] or "")
    if book["free"] > 0:
        st.badge(f"{book['free']} of {book['total']} copies free", color="green", icon="✅")
    else:
        st.badge("No copy free for these dates", color="red", icon="⛔")
    notes = []
    if book["committed"]:
        notes.append(f"{book['committed']} booked")
    if book["unavailable"]:
        notes.append(f"{book['unavailable']} out of service")
    st.caption(" · ".join(notes) or "All copies on the shelf")
    if st.button("Request to borrow", key=f"borrow_{book['book_id']}", type="primary"):
        _borrow_dialog(user, book, start, end)


@st.dialog("Request to borrow")
def _borrow_dialog(user: dict, book: dict, start, end) -> None:
    ui.cover(book["title"], book["category"])
    ui.book_heading(book["title"], book["author"] or "")
    c1, c2 = st.columns(2)
    s = c1.date_input("Start date", value=start, key=f"dlg_start_{book['book_id']}", format="DD/MM/YYYY")
    e = c2.date_input("Return by", value=end, key=f"dlg_end_{book['book_id']}", format="DD/MM/YYYY")
    st.caption(f"As a {ui.type_label(user['member_type']).lower()} you can borrow for up to "
               f"{_max_days(user)} days, both dates included. "
               "A copy is held for you while a librarian reviews the request.")
    if st.button("Submit request", type="primary", key=f"dlg_submit_{book['book_id']}"):
        try:
            booking_id = submit_request(user["id"], book["book_id"], s, e)
        except BusinessRuleError as err:
            st.error(str(err))
        else:
            ui.flash(f"Request #{booking_id} for {book['title']} submitted – awaiting librarian review. "
                     "Track it under My bookings.")
            st.rerun()


# --- My bookings ------------------------------------------------------------------------------

def my_bookings(user: dict) -> None:
    ui.section("My bookings", "Track your requests, reservations and loans.")
    bookings = repository.list_bookings(member_id=user["id"])
    overdue = _my_overdue_ids(user)
    current = [b for b in bookings if b["status"] in OPEN]
    history = [b for b in bookings if b["status"] not in OPEN]

    current_tab, history_tab = st.tabs([f"Current ({len(current)})", f"History ({len(history)})"])
    with current_tab:
        if not current:
            st.info("Nothing pending, reserved or on loan.")
            ui.nav_link("books", "Browse books", "🔎")
        for b in current:
            _booking_row(b, overdue=b["id"] in overdue, user=user)
    with history_tab:
        if not history:
            st.caption("Returned, rejected and cancelled bookings will appear here.")
        for b in history:
            _booking_row(b, overdue=False)


def _booking_row(b: dict, overdue: bool, user: dict | None = None) -> None:
    """A booking card. Pass `user` to show the cancel action."""
    with st.container(border=True):
        pic, body, side = st.columns([0.6, 4, 2.2])
        with pic:
            ui.mini_cover(b["book_title"], ui.category_of(b["book_title"]))
        with body:
            ui.book_heading(b["book_title"],
                            f"{ui.fmt(b['start_date'])} → {ui.fmt(b['end_date'])} · Copy {b['copy_code']} · #{b['id']}")
            if b["status"] == BookingStatus.REJECTED.value:
                st.caption(f"Reason: {b['note'] or '—'}. To try again, submit a new request with revised details.")
            elif b["note"]:
                st.caption(f"Note: {b['note']}")
        with side:
            ui.status_badge(b["status"], overdue=overdue)
            if user is not None and b["status"] in CANCELLABLE:
                with st.popover("Cancel booking"):
                    reason = st.text_input("Reason (optional)", key=f"cancel_reason_{b['id']}")
                    if st.button("Confirm cancellation", key=f"cancel_{b['id']}", type="primary"):
                        try:
                            cancel(b["id"], user["id"], reason)
                        except BusinessRuleError as err:
                            st.error(str(err))
                        else:
                            ui.flash(f"Booking #{b['id']} cancelled – the copy is free for others again.")
                            st.rerun()
