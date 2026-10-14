# Library Management System — Architecture & Team Plan (Group 3)

Stack: **Python 3.10+ · Streamlit (UI) · SQLite (stdlib `sqlite3`) · pytest**. No other dependencies.

---

## 1. Problem Understanding

### Stakeholders / personas
| Persona | Needs | In scope? |
|---|---|---|
| **Member** (student) | See availability, submit borrowing request, track status, cancel reservation | Yes |
| **Librarian** | Review (approve/reject) requests, issue books, accept returns, mark copies damaged/repaired/lost | Yes |
| Library Admin / Head | Analytics on demand & utilisation | Bonus (dashboard) |
| Faculty / researchers | Same as Member (could get longer loans) | Treated as Member |

### The lifecycle we support (end-to-end)
```
Member submits request ──► PENDING ──(librarian approves)──► RESERVED ──(librarian issues)──► ISSUED ──(return)──► RETURNED
                              │                                  │
                              ├─(librarian rejects)──► REJECTED  ├─(member/librarian cancels)──► CANCELLED
                              └─(member withdraws)───► CANCELLED
```
**Active statuses** (hold a copy for their date range): `PENDING`, `RESERVED`, `ISSUED`.
**Closed statuses** (release the copy): `REJECTED`, `CANCELLED`, `RETURNED`.
Closed is final — a rejected request is never edited; the member creates a new one (Rule 7).

### Copy condition (independent of bookings)
`AVAILABLE` · `DAMAGED` · `UNDER_REPAIR` · `LOST` · `REFERENCE_ONLY`
Only `AVAILABLE` copies can be allocated or issued (Rule 5).

### Business rules → where they live in code
| # | Rule | Implemented in |
|---|---|---|
| 1 | Request = member + title + start date + return date | `services/request_service.submit_request` |
| 2 | Availability = copies not committed / not unavailable for the period | `services/availability.find_free_copy` |
| 3 | No copy in two overlapping active bookings | `availability.find_free_copy` + re-check inside DB transaction |
| 4 | Block submission if no copy free | `submit_request` raises `BusinessRuleError` |
| 5 | Copies may be damaged/repair/lost/reference-only | `copies.condition` + `services/copy_service` |
| 6 | Request must be reviewed before reservation | `review_service.approve / reject` (PENDING → RESERVED) |
| 7 | Reject closes request & releases copy | `review_service.reject` (status → REJECTED, no longer "active") |
| 8 | Cancel confirmed reservation before issue releases copy | `review_service.cancel` |
| 9 | Return releases copy unless marked unavailable | `loan_service.return_book(condition=...)` |
| 10 | No partial fulfilment / alternatives; clear reason | Every rule failure raises `BusinessRuleError("<human-readable reason>")` shown in UI |

### Key assumptions (document these in README too)
1. **The copy is committed at submission** (status PENDING). This is what makes Rule 7 ("rejecting releases the commitment") meaningful and prevents two members racing for the last copy while review is pending.
2. **Dates are inclusive.** A booking 4–8 Aug overlaps one starting 8 Aug. Overlap test: `a.start <= b.end AND b.start <= a.end`.
3. **System date is configurable** (`config.TODAY`, default `2026-08-01`) so the seed data (Aug 2026) is meaningful during the demo.
4. Validations: `start_date >= TODAY`, `end_date >= start_date`, loan length ≤ **14 days**, a member may have at most **3 active** bookings.
5. Allocation picks the **lowest-id free copy** (simple, deterministic; no optimisation).
6. **Authentication excluded** — a sidebar "Act as" selector picks a seeded user/role. Reason: 90 minutes; lending lifecycle is the value, not login.
7. Marking a copy DAMAGED/LOST while it has future active bookings is allowed; the system **warns and lists affected bookings** for the librarian to cancel (auto-reassignment = next step).
8. Approve/issue re-check the copy is still `AVAILABLE`; if not, the action is refused with a reason.
9. Overdue = `ISSUED` and `end_date < TODAY` (computed, not stored). No fines.
10. Initial data table is read as: Clean Code = 4 copies, AI: A Modern Approach = 3 copies.

---

## 2. Architecture

Three layers. **UI never writes SQL; services never import Streamlit.** That is what lets 7 people work in parallel and lets us unit-test the rules.

```
┌──────────────────────────── UI (Streamlit) ─────────────────────────────┐
│ app.py  (sidebar: "Act as" user, page routing)                          │
│ ui/member_pages.py        ui/librarian_pages.py        ui/dashboard.py  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ calls functions, catches BusinessRuleError
┌───────────────────────── Services (pure Python) ────────────────────────┐
│ availability.py  request_service.py  review_service.py                  │
│ loan_service.py  copy_service.py     (all rules + state transitions)    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌──────────────────────────── Data layer ─────────────────────────────────┐
│ db.py (connection, schema, transaction helper)   seed.py (initial data) │
│ repository.py (small query helpers)               library.db (SQLite)   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Folder structure
```
Group3/
├── app.py                    # Streamlit entry: streamlit run app.py         (P1)
├── config.py                 # TODAY, MAX_LOAN_DAYS=14, MAX_ACTIVE=3, DB_PATH (P1)
├── lms/
│   ├── __init__.py
│   ├── models.py             # Status/Condition enums, BusinessRuleError      (P1)
│   ├── db.py                 # get_conn(), init_schema(), transaction()       (P2)
│   ├── seed.py               # reset_and_seed()                               (P2)
│   ├── repository.py         # read helpers: list_books, get_booking, ...     (P2)
│   └── services/
│       ├── availability.py   # overlap + find_free_copy + availability view   (P3)
│       ├── request_service.py# submit_request + validations                   (P3)
│       ├── review_service.py # approve, reject, cancel                        (P4)
│       ├── loan_service.py   # issue, return_book, overdue                    (P4)
│       └── copy_service.py   # set_condition (+ affected bookings warning)    (P4)
├── ui/
│   ├── member_pages.py       # catalogue, request form, my bookings           (P5)
│   ├── librarian_pages.py    # review queue, issue/return, copy mgmt          (P6)
│   └── dashboard.py          # BONUS: analytics + due/overdue alerts          (P1)
├── tests/
│   ├── conftest.py           # fresh temp DB per test                         (P7)
│   ├── test_availability.py  test_request.py  test_lifecycle.py               (P7)
├── docs/pitch.md (+ slides)                                                   (P7)
├── README.md                 # run, assumptions, scope, trade-offs, limits    (P1+P7)
└── requirements.txt          # streamlit, pytest
```

### Database schema (SQLite)
```sql
CREATE TABLE members (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('MEMBER','LIBRARIAN'))
);
CREATE TABLE books (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL UNIQUE, author TEXT, category TEXT
);
CREATE TABLE copies (
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id),
  copy_code TEXT UNIQUE NOT NULL,                -- e.g. CC-01
  condition TEXT NOT NULL DEFAULT 'AVAILABLE'
    CHECK (condition IN ('AVAILABLE','DAMAGED','UNDER_REPAIR','LOST','REFERENCE_ONLY'))
);
CREATE TABLE bookings (                           -- request -> reservation -> loan
  id INTEGER PRIMARY KEY,
  member_id INTEGER NOT NULL REFERENCES members(id),
  book_id INTEGER NOT NULL REFERENCES books(id),
  copy_id INTEGER NOT NULL REFERENCES copies(id),
  start_date TEXT NOT NULL, end_date TEXT NOT NULL,   -- ISO yyyy-mm-dd
  status TEXT NOT NULL CHECK (status IN
    ('PENDING','RESERVED','ISSUED','RETURNED','REJECTED','CANCELLED')),
  note TEXT,                                      -- rejection/cancel reason
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE events (                             -- audit trail / status history
  id INTEGER PRIMARY KEY, booking_id INTEGER REFERENCES bookings(id),
  action TEXT NOT NULL, actor_id INTEGER, at TEXT NOT NULL, detail TEXT
);
```
One `bookings` table with a status column (instead of separate request/reservation/loan tables) keeps the "no overlapping commitment" check to **one query**:
```sql
SELECT 1 FROM bookings
WHERE copy_id = ? AND status IN ('PENDING','RESERVED','ISSUED')
  AND start_date <= :end AND :start <= end_date
```

### Concurrency / double-booking
`submit_request` runs inside `db.transaction()` which opens `BEGIN IMMEDIATE` — the free-copy search and INSERT happen under a write lock, so two simultaneous requests cannot take the same copy.

---

## 3. Interface Contract (agree in first 10 min, then don't change without telling the team)

```python
# lms/models.py  (P1 pushes this FIRST)
class BookingStatus(str, Enum): PENDING, RESERVED, ISSUED, RETURNED, REJECTED, CANCELLED
ACTIVE_STATUSES = (PENDING, RESERVED, ISSUED)
class CopyCondition(str, Enum): AVAILABLE, DAMAGED, UNDER_REPAIR, LOST, REFERENCE_ONLY
class BusinessRuleError(Exception): """message is shown directly to the user"""

# lms/db.py  (P2)
def get_conn() -> sqlite3.Connection          # row_factory = sqlite3.Row
def init_schema(conn) -> None
@contextmanager
def transaction()                             # yields conn, BEGIN IMMEDIATE, commit/rollback

# lms/seed.py (P2)
def reset_and_seed(db_path=config.DB_PATH) -> None

# lms/repository.py (P2) — all return list[dict] / dict
def list_members(); def get_member(member_id)
def list_books(); def list_copies(book_id=None)
def list_bookings(member_id=None, status=None); def get_booking(booking_id)
def log_event(conn, booking_id, action, actor_id, detail="")

# services/availability.py (P3)
def overlaps(s1, e1, s2, e2) -> bool
def find_free_copy(conn, book_id, start, end) -> int | None
def availability_summary(start, end) -> list[dict]   # per title: total, unavailable, committed, free

# services/request_service.py (P3)
def submit_request(member_id, book_id, start: date, end: date) -> int   # booking id, raises BusinessRuleError

# services/review_service.py (P4)
def approve(booking_id, librarian_id) -> None     # PENDING -> RESERVED
def reject(booking_id, librarian_id, reason) -> None   # PENDING -> REJECTED
def cancel(booking_id, actor_id, reason="") -> None    # PENDING/RESERVED -> CANCELLED

# services/loan_service.py (P4)
def issue(booking_id, librarian_id) -> None       # RESERVED -> ISSUED
def return_book(booking_id, librarian_id, condition=CopyCondition.AVAILABLE) -> None
def list_overdue() -> list[dict]

# services/copy_service.py (P4)
def set_condition(copy_id, condition, librarian_id) -> list[dict]   # returns affected active bookings
```
Every invalid transition (e.g. approving a REJECTED booking, issuing a DAMAGED copy) raises `BusinessRuleError` with a clear sentence.

---

## 4. Work Split (7 people)

| # | Role | Owns (files) | Delivers | Must be able to explain |
|---|---|---|---|---|
| **P1** | **Tech lead & integrator** | `app.py`, `config.py`, `models.py`, `requirements.txt`, `ui/dashboard.py`, README run section | Skeleton pushed by **T+10**; merges PRs; wires pages; runs full demo; **bonus** after core works | Overall architecture, layering, why one bookings table, assumption #3 (configurable date) |
| **P2** | **Data layer** | `db.py`, `seed.py`, `repository.py` | Schema + `transaction()` + seed matching the 5 titles (incl. 2 issued, reservations, damaged copy) + 3 students + 1 librarian | Schema, CHECK constraints, how seed encodes initial data, BEGIN IMMEDIATE |
| **P3** | **Availability & request submission** | `availability.py`, `request_service.py` | Overlap logic, free-copy allocation, all submit validations (Rules 1–4, 10) | Rules 2/3/4, inclusive-date overlap, why copy is committed at submit |
| **P4** | **Lifecycle services** | `review_service.py`, `loan_service.py`, `copy_service.py` | All state transitions with guards + event logging (Rules 5–9) | State machine, Rules 6–9, what happens when copy is damaged on return |
| **P5** | **Member UI** | `ui/member_pages.py` | Catalogue with availability for chosen dates, request form (shows rule error in `st.error`), "My bookings" with status + cancel button | Member workflow, how UI shows the reason a request failed |
| **P6** | **Librarian UI** | `ui/librarian_pages.py` | Review queue (approve/reject+reason), Issue / Return (with condition dropdown), Copy management table | Librarian workflow, Rule 6 & 9 from UI side |
| **P7** | **QA, docs & pitch** | `tests/`, `docs/pitch.md`, README assumptions/trade-offs/limitations | pytest suite for every rule + conflict scenarios; 2 slides; demo script | Testing approach, how each rule was validated, known limitations |

**Parallel-work tip:** P5/P6 start immediately using **stub** service functions (return fake data) from the contract above; swap to real ones at integration. P7 writes tests against the contract from minute 10 — tests going green is the integration signal.

### Test list for P7 (minimum)
1. Overlap: touching dates overlap (inclusive); disjoint don't.
2. Submit succeeds when a copy is free; booking is PENDING with a copy.
3. Submit **fails** for Clean Code during 1–4 Aug if 2 issued + 2 other copies get booked (fill all copies).
4. Damaged copy is never allocated (Design Patterns: only 1 usable copy).
5. Reject → copy free again → another member's request succeeds.
6. Cancel RESERVED → copy free again. Cancel ISSUED → error.
7. Issue only from RESERVED; return → RETURNED; return with DAMAGED → copy not allocatable.
8. Validations: past start, end < start, > 14 days, > 3 active → errors.
9. Invalid transitions (approve twice, approve a REJECTED) → error.

---

## 5. Timeline (90 min)

| Time | Everyone |
|---|---|
| **0–10** | Read problem together, agree this contract. P1 pushes skeleton + `models.py`; P2 pushes empty `db.py` signatures. |
| **10–45** | Build in parallel on own branch (`feat/p3-availability` etc.). Small commits, PR to `main`. P7 writes tests + README assumptions + slide 1. |
| **45–60** | **Integration**: P2 → P3 → P4 merge first, then P5/P6 swap stubs for real calls. P1 runs end-to-end. |
| **60–75** | Fix bugs found by tests/demo. P1 builds bonus dashboard only if core flow works. P7 finishes slide 2. |
| **75–90** | Freeze code. Rehearse demo twice. Everyone prepares their "explain" column. |

### Git rules
- One branch per person; **each person only edits files they own** → near-zero merge conflicts.
- Commit messages: `P3: add inclusive overlap check`. Pull `main` before each PR.
- P1 is the only one merging to `main` (or require 1 review).

---

## 6. Demo Script (owner: P7, presented by all)

**Happy path (end-to-end):** Set TODAY = 1 Aug 2026.
1. Member *Asha* requests *Introduction to Algorithms* 4–8 Aug → succeeds (2 free copies remain after the existing reservation) → PENDING.
2. Librarian approves → RESERVED. Librarian issues → ISSUED.
3. Librarian records return with condition AVAILABLE → RETURNED; availability goes back up.

**Conflict / failure scenarios:**
- *Design Patterns*: Asha requests 5–10 Aug (takes the only usable copy). Ravi requests 7–9 Aug → **blocked: "No copy of Design Patterns is available from 07 Aug to 09 Aug (1 damaged, 1 already committed)."**
- Librarian **rejects** Asha → Ravi retries → succeeds (Rule 7).
- Invalid input: end before start, 20-day loan → clear messages.
- Return a copy as DAMAGED → that copy disappears from future availability (Rule 9).

---

## 7. Scope

**Included:** member request, librarian review, reservation cancel, issue, return with condition, copy condition management, availability by date range, event history, rule-level error messages, tests.
**Bonus (if time):** Dashboard — most-requested titles, copy utilisation, due-in-3-days & overdue alerts (in-app "notifications").
**Excluded (state in README):** authentication, fines, renewals, waitlists/queues, alternative-book suggestions (explicitly not required), email/SMS, multi-branch libraries.

**Trade-offs to mention in pitch:** SQLite over JSON (transactions → no double booking); single bookings table (simple overlap query vs. less separation of concepts); commit-at-submit (guarantees fairness but a pending request holds a copy until reviewed); no auth (faster delivery, but role chosen in sidebar).
