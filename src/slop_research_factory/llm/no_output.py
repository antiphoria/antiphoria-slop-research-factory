"""
NO_OUTPUT detection (D-3 §7).

When the model declares it cannot produce substantive output, the run
is sealed with a non-empty declaration string and the pipeline moves
to ``RunStatus.NO_OUTPUT`` instead of a normal draft.
"""

from __future__ import annotations

_NO_OUTPUT = "NO_OUTPUT"


def detect_no_output(text: str) -> tuple[bool, str | None]:
    """Return ``(True, explanation)`` if *text* is a NO_OUTPUT declaration.

    A NO_OUTPUT line begins (after stripping) with ``NO_OUTPUT:``; the
    remainder, if any, is the *explanation*.  The prefix is matched
    case-insensitively for the head token; the expected form is
    ``NO_OUTPUT: <reason>``.
    """
    s = text.strip()
    if not s:
        return False, None

    head, sep, rest = s.partition(":")
    if not sep or head.strip().upper() != _NO_OUTPUT:
        return False, None

    return True, (rest.strip() or None)
