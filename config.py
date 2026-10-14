"""Global settings. Change TODAY to simulate a different system date."""
from datetime import date
from pathlib import Path

DEFAULT_TODAY = date(2026, 8, 1)  # seed data is from Aug 2026
# System date used by all rules; app.py overwrites it from the sidebar.
# Always read it as config.TODAY at call time; `from config import TODAY` freezes the old value.
TODAY = DEFAULT_TODAY
DB_PATH = Path(__file__).resolve().parent / "library.db"
# Longest loan per member type, in days with both dates included.
MAX_LOAN_DAYS_BY_TYPE = {"STUDENT": 14, "RESEARCHER": 21, "PROFESSOR": 30}
MAX_ACTIVE = 3
