"""Notification gateway adapter (Docs/APIs.md §4).

Live target: DLT-registered SMS, SMTP and push.

The mock writes the delivery to the application log and returns the delivery record
the live gateway would return. Nothing leaves the machine — which matters more here
than for the other adapters: an alert escalation that accidentally reached a real
phone number during a rehearsal would be a genuine incident.

The recipient is masked in both the log line and the returned record: a delivery
log is exactly the sort of by-product that quietly accumulates personal data
(Docs/rules.md C5).
"""

from __future__ import annotations

import logging
import uuid

from app.domain.integrations.base import BaseAdapter, register, utc_now_iso

log = logging.getLogger("bhuarjan.notify")

CHANNELS = ("sms", "email", "push", "inapp")


def mask_recipient(channel: str, to: str | None) -> str | None:
    """`9876543210` -> `98••••••10`; `officer@nic.in` -> `of•••er@nic.in`.

    The domain of an email is left intact: `@nic.in` is the fact worth keeping in a
    delivery log, and it identifies an office rather than a person.
    """
    if not to:
        return None
    text = str(to)
    if "@" in text:  # an address, whatever channel it was handed to
        local, _, domain = text.partition("@")
        return f"{mask_recipient('sms', local)}@{domain}"
    if len(text) <= 4:
        return "•" * len(text)
    return f"{text[:2]}{'•' * (len(text) - 4)}{text[-2:]}"


class NotifyAdapter(BaseAdapter):
    name = "notify"
    title = "Notification gateway"
    mode = "mock"
    interface = "send(channel, to, template, vars)"
    real_target = "DLT-registered SMS, SMTP, push"
    mock_behaviour = "logs the delivery to the console; nothing leaves the machine"

    def send(
        self,
        channel: str,
        to: str,
        template: str,
        vars: dict | None = None,
        db=None,
    ) -> dict:
        """Log one delivery and return its record."""
        chan = (channel or "").strip().lower()
        record = {
            "id": str(uuid.uuid4()),
            "channel": chan,
            "to": mask_recipient(chan, to),
            "template": template,
            "vars": dict(vars or {}),
            "at": utc_now_iso(),
            "mode": self.mode,
        }
        if chan not in CHANNELS:
            record["status"] = "rejected"
            record["detail"] = f"unknown channel {channel!r}; expected one of {', '.join(CHANNELS)}"
            log.warning("notify: rejected %s", record["detail"])
            return record
        if not to:
            record["status"] = "rejected"
            record["detail"] = "no recipient supplied"
            log.warning("notify: rejected delivery with no recipient")
            return record
        record["status"] = "logged"
        record["detail"] = "console delivery; the live gateway is not wired in this build"
        log.info(
            "notify: [%s] to=%s template=%s vars=%s",
            chan, record["to"], template, record["vars"],
        )
        return record

    def _test(self, db=None) -> dict:
        record = self.send(
            "inapp",
            "admin@bhuarjan.local",
            "integration_self_test",
            {"reason": "GET /admin/integrations test button"},
        )
        return {
            "ok": record["status"] == "logged",
            "detail": f"self-test delivery {record['status']} to {record['to']} on the console",
            "delivery": record,
        }


adapter = register(NotifyAdapter())
