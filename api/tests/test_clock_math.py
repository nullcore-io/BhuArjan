"""Calendar arithmetic (Docs/rules.md C2, General Clauses Act 1897 s.3(35)).

A "month" in the Act is a British calendar month: the due date is the same day of the
target month, and the last day of that month when that day does not exist. Getting this
wrong moves a statutory deadline, so it is tested on its own, without a database.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.rules.clocks import add_duration, add_months


@pytest.mark.parametrize(
    "start,months,expected",
    [
        (date(2025, 1, 1), 12, date(2026, 1, 1)),
        (date(2025, 3, 14), 12, date(2026, 3, 14)),
        (date(2025, 11, 30), 3, date(2026, 2, 28)),   # 30 Feb does not exist
        (date(2024, 11, 29), 3, date(2025, 2, 28)),
        (date(2023, 11, 29), 3, date(2024, 2, 29)),   # leap year keeps the 29th
        (date(2025, 1, 31), 1, date(2025, 2, 28)),
        (date(2025, 8, 31), 6, date(2026, 2, 28)),
        (date(2025, 12, 15), 1, date(2026, 1, 15)),   # year rollover
        (date(2025, 6, 30), 0, date(2025, 6, 30)),
    ],
)
def test_add_months_clamps_to_the_end_of_the_target_month(start, months, expected):
    assert add_months(start, months) == expected


@pytest.mark.parametrize(
    "start,duration,expected",
    [
        (date(2025, 1, 1), {"months": 12}, date(2026, 1, 1)),
        (date(2025, 1, 1), {"years": 1}, date(2026, 1, 1)),
        (date(2025, 1, 1), {"years": 5}, date(2030, 1, 1)),
        (date(2025, 9, 27), {"days": 21}, date(2025, 10, 18)),   # 3C objections
        (date(2025, 1, 1), {"days": 60}, date(2025, 3, 2)),      # s.15(1) window
        (date(2025, 1, 1), {"months": 18}, date(2026, 7, 1)),    # s.38(1) proviso
        (date(2025, 1, 1), {}, date(2025, 1, 1)),
        (date(2025, 1, 1), None, date(2025, 1, 1)),
    ],
)
def test_add_duration(start, duration, expected):
    assert add_duration(start, duration) == expected


def test_years_and_months_and_days_compose():
    assert add_duration(date(2025, 1, 31), {"years": 1, "months": 1, "days": 1}) == date(
        2026, 3, 1
    )  # 2025-01-31 +13m -> 2026-02-28, +1d -> 2026-03-01
