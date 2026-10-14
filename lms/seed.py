"""Initial library data from the problem statement.

Safe to rerun: every run drops all tables and reloads the same data.
Run from the project root:  python -m lms.seed
"""
from datetime import date

import config
from lms.db import get_conn, init_schema, transaction

SEEDED_AT = "2026-07-21T09:00:00"
LIBRARIAN_EMAIL = "librarian@university.edu"

# (name, email, role, member type). Asha and Ravi are both students so first-come-first-served
# between equals can be shown; Anil (professor) has no bookings so priority can be demonstrated.
MEMBERS = [
    ("Asha Verma", "asha@university.edu", "MEMBER", "STUDENT"),
    ("Ravi Kumar", "ravi@university.edu", "MEMBER", "STUDENT"),
    ("Meera Iyer", "meera@university.edu", "MEMBER", "RESEARCHER"),
    ("Priya Nair", LIBRARIAN_EMAIL, "LIBRARIAN", None),
    ("Anil Mehta", "anil@university.edu", "MEMBER", "PROFESSOR"),
]

# (copy-code prefix, title, author, category, total copies, note from the source table)
# The source table merged two copy counts into the category column; read as
# Clean Code = 4 copies and AI: A Modern Approach = 3 copies.
BOOKS = [
    ("CC", "Clean Code", "Robert C. Martin", "Software Engineering", 4,
     "2 copies issued until 4 Aug 2026"),
    ("IA", "Introduction to Algorithms", "Cormen, Leiserson, Rivest, Stein", "Algorithms", 3,
     "1 copy reserved from 4 Aug 2026 to 8 Aug 2026"),
    ("DP", "Design Patterns", "Gamma, Helm, Johnson, Vlissides", "Software Design", 2,
     "1 copy unavailable due to damage"),
    ("DB", "Database System Concepts", "Silberschatz, Korth, Sudarshan", "Databases", 5,
     "All copies available"),
    ("AI", "Artificial Intelligence: A Modern Approach", "Russell, Norvig", "Artificial Intelligence", 3,
     "1 copy issued until 4 Aug 2026 and 1 copy reserved from 6 Aug 2026 to 7 Aug 2026"),
]

# copy_code -> condition, for copies that are not AVAILABLE
COPY_CONDITIONS = {"DP-1": "DAMAGED"}

# (copy_code, member email, start, end, status)
# "Issued until X" -> ISSUED; start assumed 22 Jul so loans fit the 14-day limit.
# "Reserved X-Y"   -> RESERVED (already approved by the librarian).
# Asha has no bookings so she starts the demo with a clean slate.
BOOKINGS = [
    ("CC-1", "meera@university.edu", date(2026, 7, 22), date(2026, 8, 4), "ISSUED"),
    ("CC-2", "ravi@university.edu", date(2026, 7, 22), date(2026, 8, 4), "ISSUED"),
    ("IA-1", "meera@university.edu", date(2026, 8, 4), date(2026, 8, 8), "RESERVED"),
    ("AI-1", "ravi@university.edu", date(2026, 7, 22), date(2026, 8, 4), "ISSUED"),
    ("AI-2", "meera@university.edu", date(2026, 8, 6), date(2026, 8, 7), "RESERVED"),
]

DROP_SQL = """
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS copies;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS members;
"""


def ensure_seeded(db_path=None) -> None:
    """Create and seed the database if it is missing or was built with an older schema."""
    conn = get_conn(db_path)
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(members)")}
    finally:
        conn.close()
    if "member_type" not in columns:
        reset_and_seed(db_path)


def reset_and_seed(db_path=None) -> None:
    conn = get_conn(db_path)
    conn.executescript(DROP_SQL)
    init_schema(conn)
    conn.close()

    with transaction(db_path) as conn:
        member_ids = {}
        for name, email, role, member_type in MEMBERS:
            cur = conn.execute(
                "INSERT INTO members (name, email, role, member_type) VALUES (?, ?, ?, ?)",
                (name, email, role, member_type),
            )
            member_ids[email] = cur.lastrowid

        copy_ids, copy_book_ids = {}, {}
        for prefix, title, author, category, total, _note in BOOKS:
            book_id = conn.execute(
                "INSERT INTO books (title, author, category) VALUES (?, ?, ?)",
                (title, author, category),
            ).lastrowid
            for n in range(1, total + 1):
                code = f"{prefix}-{n}"
                copy_ids[code] = conn.execute(
                    "INSERT INTO copies (book_id, copy_code, condition) VALUES (?, ?, ?)",
                    (book_id, code, COPY_CONDITIONS.get(code, "AVAILABLE")),
                ).lastrowid
                copy_book_ids[code] = book_id

        for code, email, start, end, status in BOOKINGS:
            booking_id = conn.execute(
                "INSERT INTO bookings (member_id, book_id, copy_id, start_date, end_date,"
                " status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (member_ids[email], copy_book_ids[code], copy_ids[code],
                 start.isoformat(), end.isoformat(), status, SEEDED_AT, SEEDED_AT),
            ).lastrowid
            conn.execute(
                "INSERT INTO events (booking_id, action, actor_id, at, detail)"
                " VALUES (?, 'SEEDED', ?, ?, ?)",
                (booking_id, member_ids[LIBRARIAN_EMAIL], SEEDED_AT, f"Initial data: {status}"),
            )


def print_copies(db_path=None) -> None:
    """Print every copy with its condition and active booking, grouped by title."""
    conn = get_conn(db_path)
    print(f"System date (config.TODAY): {config.TODAY}\n")
    for _prefix, title, _author, _category, total, note in BOOKS:
        print(f"{title}  [{total} copies]  source: {note}")
        rows = conn.execute(
            """
            SELECT c.copy_code, c.condition, b.status, b.start_date, b.end_date, m.name
            FROM copies c
            JOIN books bk ON bk.id = c.book_id
            LEFT JOIN bookings b ON b.copy_id = c.id
                 AND b.status IN ('PENDING', 'RESERVED', 'ISSUED')
            LEFT JOIN members m ON m.id = b.member_id
            WHERE bk.title = ?
            ORDER BY c.id, b.start_date
            """,
            (title,),
        ).fetchall()
        for r in rows:
            parts = []
            if r["condition"] != "AVAILABLE":
                parts.append(r["condition"])
            if r["status"]:
                parts.append(f"{r['status']:<9} {r['start_date']} .. {r['end_date']}  ({r['name']})")
            print(f"  {r['copy_code']:<6} {' | '.join(parts) or 'AVAILABLE'}")
        print()

    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("members", "books", "copies", "bookings")
    }
    print("Totals: " + ", ".join(f"{n} {t}" for t, n in counts.items()))
    conn.close()


if __name__ == "__main__":
    reset_and_seed()
    print_copies()
