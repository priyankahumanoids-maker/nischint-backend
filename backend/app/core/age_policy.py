"""Canonical date-of-birth and age policy for Family Circle v1.0.

Age is derived from the persisted date of birth; it is never stored as a mutable
integer. Callers can pass an explicit ``on_date`` for deterministic tests.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

ADULT_AGE_YEARS = 18


def calculate_age(date_of_birth: date, on_date: date | None = None) -> int:
    """Return completed calendar years at ``on_date``.

    February-29 birthdays advance on March 1 in non-leap years because the
    calendar anniversary has not occurred before then.
    """
    if not isinstance(date_of_birth, date):
        raise TypeError("date_of_birth must be a date")

    today = on_date or datetime.now(timezone.utc).date()
    if not isinstance(today, date):
        raise TypeError("on_date must be a date")
    if date_of_birth > today:
        raise ValueError("Date of birth cannot be in the future.")

    birthday_not_reached = (today.month, today.day) < (
        date_of_birth.month,
        date_of_birth.day,
    )
    return today.year - date_of_birth.year - int(birthday_not_reached)


def is_minor(date_of_birth: date, on_date: date | None = None) -> bool:
    """Return True when the person is younger than the launch adult age."""
    return calculate_age(date_of_birth, on_date=on_date) < ADULT_AGE_YEARS
