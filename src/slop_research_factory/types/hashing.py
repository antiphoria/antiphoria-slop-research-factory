"""Lowercase SHA-256 hex digest validation (D-2 §7, D-2 §9)."""

from __future__ import annotations

import re

SHA256_LOWERCASE_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{64}$")
"""64-character lowercase hex — canonical digest form for on-disk artifacts."""


def is_valid_sha256_hex(value: str) -> bool:
    """True if *value* is exactly 64 hex digits (a–f, 0–9)."""
    return bool(SHA256_LOWERCASE_RE.match(value))
