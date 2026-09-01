"""In-process clock evaluation schedule (worker container in v1; APScheduler for MVP)."""

import logging

log = logging.getLogger(__name__)


def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        from app.domain.alerts.service import evaluate_all_clocks

        scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
        scheduler.add_job(evaluate_all_clocks, "interval", hours=1, id="clock-eval")
        scheduler.start()
        return scheduler
    except Exception:
        log.exception("scheduler failed to start; clocks evaluate on append only")
        return None
