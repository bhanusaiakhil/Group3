"""SQLite connection, schema and transaction helper."""
import sqlite3
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('MEMBER','LIBRARIAN')),
  member_type TEXT CHECK (member_type IN ('STUDENT','RESEARCHER','PROFESSOR')),
  CHECK ((role = 'LIBRARIAN') = (member_type IS NULL))   -- every member has a type, librarians none
);

CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL UNIQUE,
  author TEXT,
  category TEXT
);

CREATE TABLE IF NOT EXISTS copies (
  id INTEGER PRIMARY KEY,
  book_id INTEGER NOT NULL REFERENCES books(id),
  copy_code TEXT UNIQUE NOT NULL,
  condition TEXT NOT NULL DEFAULT 'AVAILABLE'
    CHECK (condition IN ('AVAILABLE','DAMAGED','UNDER_REPAIR','LOST','REFERENCE_ONLY'))
);

CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY,
  member_id INTEGER NOT NULL REFERENCES members(id),
  book_id INTEGER NOT NULL REFERENCES books(id),
  copy_id INTEGER NOT NULL REFERENCES copies(id),
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN
    ('PENDING','RESERVED','ISSUED','RETURNED','REJECTED','CANCELLED')),
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_bookings_copy_status ON bookings(copy_id, status);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  booking_id INTEGER REFERENCES bookings(id),
  action TEXT NOT NULL,
  actor_id INTEGER,
  at TEXT NOT NULL,
  detail TEXT
);
"""


def get_conn(db_path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # transactions are opened explicitly via transaction()
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn) -> None:
    conn.executescript(SCHEMA)


@contextmanager
def transaction(db_path=None):
    """Yield a connection inside BEGIN IMMEDIATE; commit on success, roll back on error."""
    conn = get_conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
