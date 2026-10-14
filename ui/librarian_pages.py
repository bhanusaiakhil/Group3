"""Librarian pages: desk home, review queue, issue & return, inventory, members, activity.

Presentation only: every rule lives in the services; these pages show their results and errors.
"""
import streamlit as st

import config
from lms import repository
from lms.models import MEMBER_PRIORITY, BookingStatus, BusinessRuleError, CopyCondition
from lms.services.copy_service import set_condition
from lms.services.loan_service import issue, list_overdue, return_book
from lms.services.review_service import approve, cancel, reject
from ui import components as ui

CONDITIONS = [c.value for c in CopyCondition]  # AVAILABLE first = default


def _label(condition: str) -> str:
    return condition.replace("_", " ").capitalize()


def _attempt(fn, *args, success: str, copy_code: str = "") -> None:
    """Call a service; show its rule error, or rerun with a success message.

    set_condition / return_book return the copy's other active bookings: shown as a warning.
    """
    try:
        affected = fn(*args)
    except BusinessRuleError as e:
        st.error(str(e))
        return
    ui.flash(success)
    if affected:
        lines = "\n".join(
            f"- #{b['id']} · {b['member_name']} · {b['status']} · {ui.fmt(b['start_date'])} → {ui.fmt(b['end_date'])}"
            for b in affected
        )
        ui.flash(f"Copy {copy_code} is now unavailable but these bookings still use it. "
                 f"Cancel them if it will not be back in time:\n\n{lines}", kind="warning")
    st.rerun()


def _card(b: dict):
    """Booking card: small cover on the left; returns the right-hand column for details and actions."""
    pic, body = st.columns([0.6, 5])
    with pic:
        ui.mini_cover(b["book_title"], ui.category_of(b["book_title"]))
    with body:
        ui.book_heading(b["book_title"],
                        f"{b['member_name']} ({ui.type_label(b['member_type'])}) · "
                        f"{ui.fmt(b['start_date'])} → {ui.fmt(b['end_date'])} · Copy {b['copy_code']} · #{b['id']}")
    return body


# --- Home -------------------------------------------------------------------------------------

def home(user: dict) -> None:
    ui.hero("Librarian desk", "Review requests, hand out books and keep the collection in shape.",
            eyebrow=f"Campus Library · {ui.fmt(config.TODAY)}")
    pending = repository.list_bookings(status=BookingStatus.PENDING)
    reserved = repository.list_bookings(status=BookingStatus.RESERVED)
    issued = repository.list_bookings(status=BookingStatus.ISSUED)
    overdue = list_overdue()
    out_of_service = [c for c in repository.list_copies() if c["condition"] != CopyCondition.AVAILABLE.value]

    cols = st.columns(5)
    cols[0].metric("Waiting for review", len(pending), border=True)
    cols[1].metric("Reservations", len(reserved), border=True)
    cols[2].metric("On loan", len(issued), border=True)
    cols[3].metric("Overdue", len(overdue), border=True)
    cols[4].metric("Copies out of service", len(out_of_service), border=True)

    left, right = st.columns([3, 2], gap="large")
    with left:
        ui.section("Recent activity")
        events = repository.list_events(6)
        with st.container(border=True):
            if not events:
                st.caption("No activity yet.")
            for e in events:
                st.markdown(f"**{e['action'].replace('_', ' ').title()}** · {e['actor_name'] or 'System'}  \n"
                            f":gray[{e['at'].replace('T', ' ')} · {e['detail']}]")
    with right:
        ui.section("Quick links")
        with st.container(border=True):
            ui.nav_link("review", f"Review queue ({len(pending)})", "📥")
            ui.nav_link("loans", "Issue & return", "🔁")
            ui.nav_link("inventory", "Inventory", "🗂️")
            ui.nav_link("members", "Members and borrowing limits", "👥")
        if overdue:
            st.warning(f"{len(overdue)} loan(s) overdue – see Issue & return.", icon="⚠️")


# --- Review queue -----------------------------------------------------------------------------

def review_queue(user: dict) -> None:
    ui.section("Review queue", "Highest priority first (Professor > Researcher > Student), then oldest. "
               "Each request already holds a copy: approving reserves it; rejecting releases it.")
    pending = sorted(repository.list_bookings(status=BookingStatus.PENDING),
                     key=lambda b: (-MEMBER_PRIORITY.get(b["member_type"], 0), b["created_at"], b["id"]))
    if not pending:
        st.success("All caught up – no requests waiting for review.", icon="🎉")
        return
    for b in pending:
        with st.container(border=True), _card(b):
            ui.type_badge(b["member_type"])
            a, r, _ = st.columns([1, 1, 3])
            if a.button("Approve", key=f"approve_{b['id']}", type="primary", icon="✅"):
                _attempt(approve, b["id"], user["id"], success=f"Booking #{b['id']} approved – copy reserved.")
            with r.popover("Reject", icon="✖️"):
                reason = st.text_input("Reason (required)", key=f"reject_reason_{b['id']}")
                if st.button("Confirm rejection", key=f"reject_{b['id']}", type="primary"):
                    _attempt(reject, b["id"], user["id"], reason,
                             success=f"Booking #{b['id']} rejected – copy {b['copy_code']} released.")


# --- Issue & return ---------------------------------------------------------------------------

def loans(user: dict) -> None:
    ui.section("Issue & return", "Hand out reserved books and record returns, including the copy's condition.")
    reserved = sorted(repository.list_bookings(status=BookingStatus.RESERVED), key=lambda b: b["start_date"])
    issued = sorted(repository.list_bookings(status=BookingStatus.ISSUED), key=lambda b: b["end_date"])
    overdue = {o["id"]: o["days_overdue"] for o in list_overdue()}

    late = f" · ⚠️ {len(overdue)} overdue" if overdue else ""
    to_issue_tab, on_loan_tab = st.tabs([f"To issue ({len(reserved)})", f"On loan ({len(issued)}){late}"])
    with to_issue_tab:
        if not reserved:
            st.caption("No confirmed reservations.")
        for b in reserved:
            with st.container(border=True), _card(b):
                i, c, _ = st.columns([1, 1, 3])
                if i.button("Issue", key=f"issue_{b['id']}", type="primary", icon="📤"):
                    _attempt(issue, b["id"], user["id"], success=f"Booking #{b['id']} issued to {b['member_name']}.")
                if c.button("Cancel", key=f"cancel_{b['id']}"):
                    _attempt(cancel, b["id"], user["id"],
                             success=f"Reservation #{b['id']} cancelled – copy {b['copy_code']} released.")
    with on_loan_tab:
        if not issued:
            st.caption("Nothing on loan.")
        for b in issued:
            with st.container(border=True), _card(b):
                if b["id"] in overdue:
                    st.badge(f"Overdue by {overdue[b['id']]} day(s)", color="red", icon="⚠️")
                else:
                    st.badge(f"Due {ui.fmt(b['end_date'])}", color="violet", icon="📖")
                cond, ret, _ = st.columns([2, 1, 2])
                condition = cond.selectbox("Condition on return", CONDITIONS, format_func=_label,
                                           key=f"return_condition_{b['id']}")
                ret.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
                if ret.button("Return", key=f"return_{b['id']}", type="primary", icon="📥"):
                    _attempt(return_book, b["id"], user["id"], condition, copy_code=b["copy_code"],
                             success=f"Booking #{b['id']} returned; copy {b['copy_code']} is {_label(condition)}.")


# --- Inventory --------------------------------------------------------------------------------

def inventory(user: dict) -> None:
    ui.section("Inventory", "Every physical copy and its condition. Only available copies can be lent.")
    copies = repository.list_copies()
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.dataframe(
            [{"Copy": c["copy_code"], "Title": c["book_title"],
              "Condition": ("🟢 " if c["condition"] == CopyCondition.AVAILABLE.value else "🔴 ") + _label(c["condition"])}
             for c in copies],
            hide_index=True, height=420,
        )
    with right:
        labels = {c["id"]: f"{c['copy_code']} – {c['book_title']}" for c in copies}
        codes = {c["id"]: c["copy_code"] for c in copies}
        with st.form("condition_form", border=True):
            st.markdown("**Change a copy's condition**")
            copy_id = st.selectbox("Copy", list(labels), format_func=labels.get, key="condition_copy")
            condition = st.selectbox("New condition", CONDITIONS, format_func=_label, key="condition_value")
            submitted = st.form_submit_button("Update condition", type="primary")
        if submitted:
            _attempt(set_condition, copy_id, condition, user["id"], copy_code=codes[copy_id],
                     success=f"Copy {codes[copy_id]} is now {_label(condition)}.")


# --- Members ----------------------------------------------------------------------------------

def members(user: dict) -> None:
    ui.section("Members", "Who can borrow, for how long, and their priority when requests clash.")
    active = {}
    for b in repository.list_bookings():
        if b["status"] in (BookingStatus.PENDING.value, BookingStatus.RESERVED.value, BookingStatus.ISSUED.value):
            active[b["member_id"]] = active.get(b["member_id"], 0) + 1
    rows = sorted((m for m in repository.list_members() if m["member_type"]),
                  key=lambda m: (-MEMBER_PRIORITY[m["member_type"]], m["name"]))
    rank = {3: "1 (highest)", 2: "2", 1: "3 (lowest)"}
    st.dataframe(
        [{"Name": m["name"], "Type": ui.type_label(m["member_type"]),
          "Priority": rank[MEMBER_PRIORITY[m["member_type"]]],
          "Max loan (days)": config.MAX_LOAN_DAYS_BY_TYPE[m["member_type"]],
          "Active bookings": f"{active.get(m['id'], 0)} / {config.MAX_ACTIVE}", "Email": m["email"]}
         for m in rows],
        hide_index=True,
    )
    st.caption("When a higher-priority member requests a copy held only by lower-priority requests that are "
               "still waiting for review, those requests are closed with a reason and their owners are told "
               "to request other dates. Confirmed reservations and loans are never taken away.")


# --- Activity ---------------------------------------------------------------------------------

def activity(user: dict) -> None:
    ui.section("Activity", "The latest 20 actions, newest first.")
    events = repository.list_events(20)
    if not events:
        st.info("No activity yet.")
        return
    st.dataframe(
        [{"When": e["at"].replace("T", " "), "Action": e["action"].replace("_", " ").title(),
          "By": e["actor_name"] or "System", "Booking": f"#{e['booking_id']}" if e["booking_id"] else "",
          "Book": e["book_title"] or "", "Detail": e["detail"]} for e in events],
        hide_index=True,
    )
