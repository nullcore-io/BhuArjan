"""The statutory day (Docs/rules.md C2).

Every deadline in the Act runs on the Indian calendar: a notification published on
31 January is out of time on 1 February *in India*, whatever the clock on the server
says. The containers run UTC (api/Dockerfile sets no TZ), so `date.today()` there is
still the previous day until 05:30 IST — long enough for the 01:00 sweep, scheduled on
the Asia/Kolkata calendar, to report a breached clock as running.

So nothing that decides statutory state may ask the process what day it is. It asks
here instead.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def ist_now() -> datetime:
    """Now, in Indian Standard Time."""
    return datetime.now(IST)


def ist_today() -> date:
    """Today's date in IST — the statutory 'today' everywhere in this system."""
    return ist_now().date()
