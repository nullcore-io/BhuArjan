"""The adapter protocol and its registry (Docs/APIs.md §4).

Every one of the six adapters in this build is a **mock**, and says so: `mode` is
data on the adapter itself, `GET /admin/integrations` reads it from here, and the
screen shown on stage prints it. APIs.md §4 is explicit that we say it out loud
rather than let a demo imply a live PFMS connection that does not exist.

What the mocks are *not* is fake: each one answers from something real in this
system — the parcels table, the event ledger, the seeded gazette PDFs, MinIO — so
the shape of every reply is the shape the live adapter would have to produce. The
one place that would need more than a swapped base URL is `digilocker`, which
returns an issuance envelope without stamping the PDF; its `detail` says so.

`test()` never raises: an adapter that cannot reach its dependency reports
`{ok: false, detail: ...}`, because the admin screen's job is to show that state,
not to 500 on it. The result is remembered on the instance as `last_test` — an
in-process fact, lost on restart, which is honest for a demo and is why the field
is named after the call rather than after a "sync".
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

log = logging.getLogger(__name__)

MOCK = "mock"
LIVE = "live"

# The table order of Docs/APIs.md §4 — the admin screen lists them in it.
ADAPTER_ORDER = ("ulpin", "pfms", "gazette", "digilocker", "gatishakti", "notify")


class Adapter(Protocol):
    """What every adapter must offer. Domain calls (`lookup`, `send`, ...) are
    adapter-specific and documented on each class; this is the common part the
    registry and the admin endpoints rely on."""

    name: str
    mode: str

    def test(self, db: Any = None) -> dict:
        """`{ok: bool, detail: str, ...}` — never raises."""


def mask_ref(value: str | None, keep: int = 2) -> str | None:
    """Mask an owner reference for display (Docs/rules.md C5).

    `owner_ref` is already a pseudonymous reference rather than a name, but the
    ULPIN adapter is the one surface where a land record and a person meet, so it
    leaves only enough to recognise a record you already hold.
    """
    if value is None:
        return None
    text = str(value)
    if len(text) <= keep * 2:
        return "•" * len(text)
    return f"{text[:keep]}{'•' * (len(text) - keep * 2)}{text[-keep:]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseAdapter:
    """Shared plumbing: describe() for the admin list, test() for the test button.

    Subclasses set the class attributes and implement `_test`.
    """

    name: str = ""
    title: str = ""
    mode: str = MOCK
    interface: str = ""
    real_target: str = ""
    mock_behaviour: str = ""
    # Interface members named in APIs.md §4 that this build does NOT implement.
    # Listed rather than stubbed, so the admin screen cannot claim them.
    deferred: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.last_test: dict | None = None

    # --- to implement -------------------------------------------------------------

    def _test(self, db: Any = None) -> dict:
        raise NotImplementedError

    # --- common -------------------------------------------------------------------

    def test(self, db: Any = None) -> dict:
        """Run the adapter's self-check. Records and returns the outcome."""
        try:
            result = dict(self._test(db))
        except Exception as exc:  # an unreachable dependency is a result, not a 500
            log.warning("integrations: %s test failed: %s", self.name, exc)
            result = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        result.setdefault("ok", False)
        result.setdefault("detail", "")
        result["ok"] = bool(result["ok"])
        result["name"] = self.name
        result["mode"] = self.mode
        result["at"] = utc_now_iso()
        self.last_test = {
            "at": result["at"],
            "ok": result["ok"],
            "detail": result["detail"],
        }
        return result

    def describe(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "mode": self.mode,
            "interface": self.interface,
            "real_target": self.real_target,
            "mock_behaviour": self.mock_behaviour,
            "deferred": list(self.deferred),
            "last_test": self.last_test,
        }


# --- registry -----------------------------------------------------------------------

_REGISTRY: dict[str, BaseAdapter] = {}
_loaded = False


def register(adapter: BaseAdapter) -> BaseAdapter:
    """Add (or replace) an adapter under its own name."""
    if not adapter.name:
        raise ValueError("adapter needs a name")
    _REGISTRY[adapter.name] = adapter
    return adapter


def _load_builtin() -> None:
    """Import the six adapter modules; each registers one instance on import."""
    global _loaded
    if _loaded:
        return
    _loaded = True  # set first: a failing import must not retry on every request
    from app.domain.integrations import (  # noqa: F401
        digilocker,
        gatishakti,
        gazette,
        notify,
        pfms,
        ulpin,
    )


def get_adapter(name: str) -> BaseAdapter | None:
    """The adapter called `name`, or None — callers turn that into a 404."""
    _load_builtin()
    return _REGISTRY.get((name or "").strip().lower())


def list_adapters() -> list[BaseAdapter]:
    """Every registered adapter, in the order of the APIs.md §4 table."""
    _load_builtin()
    known = [_REGISTRY[n] for n in ADAPTER_ORDER if n in _REGISTRY]
    extra = [a for n, a in sorted(_REGISTRY.items()) if n not in ADAPTER_ORDER]
    return known + extra
