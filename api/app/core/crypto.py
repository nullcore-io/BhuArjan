"""Field-level PII encryption — AES-256-GCM (Docs/rules.md C5, Docs/Backend.md §10).

Demo: key from environment (PII_KEY, 64 hex chars) with a dev default. Production:
KMS-backed key. Every decrypt is the caller's responsibility to audit
(admin_audit PII_READ with purpose) — this module only does the cryptography.

Ciphertext layout: nonce(12) || ciphertext || tag(16), as produced by AESGCM.
"""

import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DEV_KEY_HEX = "6b" * 32  # dev only; overridden by PII_KEY


def _key() -> bytes:
    return bytes.fromhex(os.environ.get("PII_KEY", _DEV_KEY_HEX))


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
