"""Shared look and feel: theme CSS, hero banner, book covers, status badges, flash messages, footer."""
import html
from datetime import date

import streamlit as st

from lms import repository
from lms.models import BookingStatus as S

_CSS = """
<style>
:root { --ink:#1f2933; --muted:#6b7280; --navy:#1d3557; --teal:#2a9d8f; }
.block-container { padding-top: 4.4rem; max-width: 1180px; }
.hero { background: linear-gradient(120deg, #1d3557 0%, #27496d 55%, #2a9d8f 100%); color:#fff;
        border-radius:18px; padding:2.1rem 2.4rem; margin:0.4rem 0 1.4rem;
        box-shadow:0 12px 30px rgba(29,53,87,.18); }
.hero-eyebrow { text-transform:uppercase; letter-spacing:.14em; font-size:.74rem; font-weight:600; opacity:.85; }
.hero-title { font-size:2.05rem; font-weight:750; line-height:1.15; margin:.35rem 0 .45rem; }
.hero-sub { font-size:1.04rem; opacity:.92; max-width:660px; }
.cover { border-radius:12px; height:128px; display:flex; align-items:flex-end; justify-content:space-between;
         padding:.75rem .95rem; color:#fff; margin-bottom:.7rem; box-shadow:inset 0 -40px 60px rgba(0,0,0,.12); }
.cover .initials { font-size:2.3rem; font-weight:800; letter-spacing:.02em; text-shadow:0 2px 8px rgba(0,0,0,.25); }
.cover .cat { font-size:.66rem; text-transform:uppercase; letter-spacing:.08em; background:rgba(255,255,255,.22);
              padding:.22rem .55rem; border-radius:999px; }
.mini-cover { width:54px; height:70px; border-radius:8px; display:flex; align-items:center; justify-content:center;
              color:#fff; font-weight:800; font-size:1.05rem; }
.book-title { font-weight:700; font-size:1.04rem; line-height:1.3; color:var(--ink); }
.book-meta { color:var(--muted); font-size:.86rem; margin:.1rem 0 .45rem; }
.section-title { font-size:1.25rem; font-weight:700; color:var(--ink); margin:1.2rem 0 .2rem; }
.section-sub { color:var(--muted); font-size:.92rem; margin-bottom:.8rem; }
.site-footer { margin-top:3rem; padding:1.1rem 0 .4rem; border-top:1px solid rgba(0,0,0,.08); color:var(--muted);
               font-size:.84rem; display:flex; justify-content:space-between; flex-wrap:wrap; gap:.5rem; }
</style>
"""

_COVER_COLORS = {
    "Software Engineering": ("#1d3557", "#457b9d"),
    "Algorithms": ("#6a4c93", "#9d79bc"),
    "Software Design": ("#bc4749", "#e07a5f"),
    "Databases": ("#2a9d8f", "#52b69a"),
    "Artificial Intelligence": ("#e76f51", "#f4a261"),
}
_DEFAULT_COLORS = ("#3d405b", "#81b29a")

# status -> (label, badge colour, icon)
_STATUS = {
    S.PENDING.value: ("Pending review", "orange", "🕒"),
    S.RESERVED.value: ("Reserved – ready to collect", "blue", "📌"),
    S.ISSUED.value: ("On loan", "violet", "📖"),
    S.RETURNED.value: ("Returned", "green", "✅"),
    S.REJECTED.value: ("Rejected", "red", "❌"),
    S.CANCELLED.value: ("Cancelled", "gray", "🚫"),
}

_FLASH = "_flash"


def apply_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, eyebrow: str = "Campus Library") -> None:
    st.markdown(
        f'<div class="hero"><div class="hero-eyebrow">{html.escape(eyebrow)}</div>'
        f'<div class="hero-title">{html.escape(title)}</div>'
        f'<div class="hero-sub">{html.escape(subtitle)}</div></div>',
        unsafe_allow_html=True,
    )


def section(title: str, subtitle: str = "") -> None:
    sub = f'<div class="section-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(f'<div class="section-title">{html.escape(title)}</div>{sub}', unsafe_allow_html=True)


def _initials(title: str) -> str:
    words = [w for w in title.replace(":", " ").split() if w[0].isalpha() and w.lower() not in {"a", "an", "the", "to", "of"}]
    return "".join(w[0] for w in words[:2]).upper()


def _gradient(category: str | None) -> str:
    c1, c2 = _COVER_COLORS.get(category or "", _DEFAULT_COLORS)
    return f"linear-gradient(135deg, {c1}, {c2})"


def cover(title: str, category: str | None) -> None:
    st.markdown(
        f'<div class="cover" style="background:{_gradient(category)}">'
        f'<span class="initials">{_initials(title)}</span>'
        f'<span class="cat">{html.escape(category or "")}</span></div>',
        unsafe_allow_html=True,
    )


def category_of(title: str) -> str | None:
    return next((b["category"] for b in repository.list_books() if b["title"] == title), None)


def mini_cover(title: str, category: str | None) -> None:
    st.markdown(
        f'<div class="mini-cover" style="background:{_gradient(category)}">{_initials(title)}</div>',
        unsafe_allow_html=True,
    )


def book_heading(title: str, meta: str) -> None:
    st.markdown(
        f'<div class="book-title">{html.escape(title)}</div><div class="book-meta">{html.escape(meta)}</div>',
        unsafe_allow_html=True,
    )


def status_badge(status: str, overdue: bool = False, container=st) -> None:
    if overdue:
        container.badge("Overdue – please return", color="red", icon="⚠️")
        return
    label, color, icon = _STATUS.get(status, (status, "gray", None))
    container.badge(label, color=color, icon=icon)


_TYPE_BADGES = {"PROFESSOR": ("violet", "🎓"), "RESEARCHER": ("blue", "🔬"), "STUDENT": ("gray", "🎒")}


def type_label(member_type: str | None) -> str:
    return (member_type or "Librarian").title()


def type_badge(member_type: str | None, container=st) -> None:
    color, icon = _TYPE_BADGES.get(member_type or "", ("gray", None))
    container.badge(type_label(member_type), color=color, icon=icon)


def fmt(iso: str | date) -> str:
    d = date.fromisoformat(iso) if isinstance(iso, str) else iso
    return d.strftime("%d %b %Y")


def flash(message: str, kind: str = "success") -> None:
    """Queue a message to show after st.rerun() (which would otherwise erase it)."""
    st.session_state.setdefault(_FLASH, []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop(_FLASH, []):
        getattr(st, kind)(message)


def register_nav(pages: dict) -> None:
    st.session_state["_nav"] = pages


def nav_link(url_path: str, label: str, icon: str | None = None) -> None:
    """Link to another page of this site (only if the current role can see it)."""
    target = st.session_state.get("_nav", {}).get(url_path)
    if target is not None:
        st.page_link(target, label=label, icon=icon)


def footer() -> None:
    st.markdown(
        '<div class="site-footer"><span>📚 Campus Library · Library Management System</span>'
        "<span>Group 3 prototype · runs locally, no personal data</span></div>",
        unsafe_allow_html=True,
    )
