"""Field-level PII encryption — AES-256-GCM (Docs/rules.md C5, Docs/Backend.md §10).

The key comes from `settings.PII_KEY` (64 hex characters), which pydantic-settings
reads from the environment *or* from `api/.env`. It is deliberately **not** read from
`os.environ` directly: `.env` is loaded into the settings object and never exported to
the process environment, so an `os.environ` read meant every deployment that
configured the key the documented way silently kept encrypting under the development
constant below.

Outside `DEMO_MODE` a missing or development key is a hard failure — at first use here
and, before that, at startup (`app.main.lifespan` calls `assert_key_configured`), so
the failure is a refusal to boot rather than a database full of PII encrypted under a
key that is published in this file. Production supplies a KMS-backed key.

Ciphertext layout: nonce(12) || ciphertext || tag(16), as produced by AESGCM.
"""

import json
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

log = logging.getLogger(__name__)

_DEV_KEY_HEX = "6b" * 32  # dev only; overridden by settings.PII_KEY
KEY_BYTES = 32


def key_problem() -> str | None:
    """Why the configured key may not be used, or None when it may.

    One question, asked identically by `_key()` and by the startup check, so the API
    can never boot on a key the first decrypt would reject.
    """
    configured = (settings.PII_KEY or "").strip()
    if configured and configured.lower() != _DEV_KEY_HEX:
        try:
            raw = bytes.fromhex(configured)
        except ValueError:
            return "PII_KEY is not hexadecimal; it must be 64 hex characters (32 bytes)"
        if len(raw) != KEY_BYTES:
            return (
                f"PII_KEY decodes to {len(raw)} bytes; AES-256-GCM needs "
                f"{KEY_BYTES} (64 hex characters)"
            )
        return None
    if settings.DEMO_MODE:
        return None
    return (
        "PII_KEY is unset or still the development constant, and DEMO_MODE is false: "
        "affected-family PII would be encrypted under a key published in this "
        "repository (Docs/rules.md C5, Docs/Backend.md §10). Supply a 64-hex "
        "KMS-backed key in PII_KEY."
    )


def assert_key_configured() -> None:
    """Startup guard — refuse to run outside DEMO_MODE without a real key."""
    problem = key_problem()
    if problem is None:
        return
    log.error("refusing to start: %s", problem)
    raise RuntimeError(problem)


def _key() -> bytes:
    problem = key_problem()
    if problem is not None:
        raise RuntimeError(problem)
    configured = (settings.PII_KEY or "").strip()
    if configured and configured.lower() != _DEV_KEY_HEX:
        return bytes.fromhex(configured)
    return bytes.fromhex(_DEV_KEY_HEX)


def encrypt_pii(fields: dict) -> bytes:
    """dict -> AES-GCM blob. Canonical JSON so equal dicts encrypt comparably-sized."""
    nonce = os.urandom(12)
    data = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
    return nonce + AESGCM(_key()).encrypt(nonce, data, None)


def decrypt_pii(blob: bytes) -> dict:
    """AES-GCM blob -> dict. Raises on tamper (InvalidTag)."""
    blob = bytes(blob)
    return json.loads(AESGCM(_key()).decrypt(blob[:12], blob[12:], None))


def mask_name(fields: dict) -> str:
    """Public-safe reference: initials only — never a name (rules.md C5)."""
    name = str(fields.get("name", ""))
    initials = "".join(w[0].upper() for w in name.split() if w)[:3]
    return f"Family {initials or '—'}"
