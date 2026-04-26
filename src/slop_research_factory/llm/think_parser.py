"""
Extract optional &quot;reasoning / chain-of-thought&quot; blocks from model text.

Handles common OpenWebUI / DeepSeek style ``<details>…</details>`` wrappers
and ``<think>`` blocks (D-0 §4A).  Everything else is left in
*final_output* with surrounding whitespace normalised.
"""

from __future__ import annotations

import re

_DETAILS_BLOCK = re.compile(
    r"<details\b[^>]*>.*?</details>",
    re.DOTALL | re.IGNORECASE,
)
_REDACTED = re.compile(
    r"<redacted_thinking\b[^>]*>.*?</think>",
    re.DOTALL | re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")


def _strip_minimal_html(text: str) -> str:
    return _TAG.sub("", text).strip()


def parse_think_tokens(content: str) -> tuple[str | None, str]:
    """Split *content* into (think_trace, final_output).

    If a structured think block is found, the trace is the inner text
    (tags stripped) and the remainder is the draft.  If multiple blocks
    exist, the first is treated as the think trace; remaining content
    after removal is the draft.
    """
    if not content or not content.strip():
        return None, ""

    work = content

    # Prefer explicit redacted block if present
    m_red = _REDACTED.search(work)
    if m_red:
        think = _strip_minimal_html(m_red.group(0)) or None
        rest = _REDACTED.sub("", work, count=1)
        return think, rest.strip()

    m_det = _DETAILS_BLOCK.search(work)
    if m_det:
        think = _strip_minimal_html(m_det.group(0)) or None
        rest = _DETAILS_BLOCK.sub("", work, count=1)
        return think, rest.strip()

    return None, work.strip()
