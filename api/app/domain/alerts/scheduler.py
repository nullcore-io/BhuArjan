"""In-process clock evaluation schedule (worker container in v1; APScheduler for MVP).

Two jobs, both on the Asia/Kolkata calendar because both decide statutory facts:

    clock-eval        hourly — bring every open case's clocks up to today (§5, §9)
    chain-integrity   02:00 IST nightly — re-verify every case's hash chain (C1, §4)
"""

import logging

log = logging.getLogger(__name__)

TIMEZONE = "Asia/Kolkata"


def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        from app.domain.alerts.service import evaluate_all_clocks, verify_all_chains

        scheduler = BackgroundScheduler(timezone=TIMEZONE)
        scheduler.add_job(evaluate_all_clocks, "interval", hours=1, id="clock-eval")
        scheduler.add_job(
            verify_all_chains,
            "cron",
            hour=2,
            timezone=TIMEZONE,
            id="chain-integrity",
        )
        scheduler.start()
        return scheduler
    except Exception:
        log.exception("scheduler failed to start; clocks evaluate on append only")
        return None
