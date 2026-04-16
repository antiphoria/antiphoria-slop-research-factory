# src/slop_research_factory/prompts/__init__.py

"""
Prompt-file loader for the antiphoria slop-research-factory.

All prompts are stored as plain text files in subdirectories of
this package, organised by node role.  Each file carries a
two-line documentary header that mirrors D-3's specification
layout (title + ``═`` separator).  The loader strips this header
by default so callers receive clean text ready for LLM messages.

File naming convention  (D-3 §11)::

    {role}/{kind}_{version}.txt

    generator/system_v0.1.txt
    verifier/user_template_v0.1.txt

Reference
---------
D-3 §11 — Prompt File Organisation.
D-3 §3  — Generator Prompt.
D-3 §4  — Verifier Prompt.
D-3 §5  — Reviser Prompt.
D-3 §6  — Citation Extraction Prompt.
"""

from pathlib import Path

__all__ = [
    "PROMPT_VERSION",
    "VALID_KINDS",
    "VALID_ROLES",
    "load_prompt",
]

PROMPT_VERSION: str = "v0.1"
"""Current default prompt version string."""

VALID_ROLES: frozenset[str] = frozenset({
    "citation_extractor",
    "generator",
    "reviser",
    "verifier",
})
"""Closed set of node roles that have prompt files."""

VALID_KINDS: frozenset[str] = frozenset({
    "system",
    "user_template",
})
"""Closed set of prompt-file kinds."""

_PROMPT_DIR: Path = Path(__file__).resolve().parent

# U+2550 — BOX DRAWINGS DOUBLE HORIZONTAL  (the ═ character)

_SEPARATOR_CHAR: str = "\u2550"


def _strip_documentary_header(text: str) -> str:
    """Remove the D-3 documentary header from raw file text.

    Each prompt file carries a two-line header::

        SYSTEM PROMPT — GENERATOR NODE
        ═══════════════════════════════
        <prompt body>

    This function locates the first separator line (composed
    entirely of ``═`` characters) and returns everything after
    it, with leading/trailing whitespace stripped.

    If no separator is found the full text is returned as-is
    (defensive: the file is still usable if someone removes
    the header).
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and all(
            ch == _SEPARATOR_CHAR for ch in stripped
        ):
            return "\n".join(lines[i + 1:]).strip()
    # No separator found — return full text unchanged.
    return text.strip()


def load_prompt(
    role: str,
    kind: str,
    *,
    version: str = PROMPT_VERSION,
    strip_header: bool = True,
) -> str:
    """Load a prompt text file by *role*, *kind*, and *version*.

    Parameters
    ----------
    role:
        Node role.  One of :data:`VALID_ROLES`.
    kind:
        Prompt kind.  One of :data:`VALID_KINDS`.
    version:
        Prompt version string (default: current
        :data:`PROMPT_VERSION`).
    strip_header:
        When ``True`` (default) the D-3 documentary header
        is removed before the text is returned.  Set to
        ``False`` for audit comparisons against the
        specification text.

    Returns
    -------
    str
        Prompt text ready for LLM message construction
        (system prompts) or template rendering (user
        templates).

    Raises
    ------
    ValueError
        If *role* or *kind* is not in the valid set.
    FileNotFoundError
        If the prompt file does not exist on disk.
    """
    if role not in VALID_ROLES:
        msg = (
            f"role must be one of {sorted(VALID_ROLES)}, "
            f"got {role!r}"
        )
        raise ValueError(msg)

    if kind not in VALID_KINDS:
        msg = (
            f"kind must be one of {sorted(VALID_KINDS)}, "
            f"got {kind!r}"
        )
        raise ValueError(msg)

    filename = f"{kind}_{version}.txt"
    filepath = _PROMPT_DIR / role / filename

    if not filepath.is_file():
        msg = (
            f"Prompt file not found: {filepath}  "
            f"(role={role!r}, kind={kind!r}, "
            f"version={version!r})"
        )
        raise FileNotFoundError(msg)

    raw = filepath.read_text(encoding="utf-8")

    if strip_header:
        return _strip_documentary_header(raw)
    return raw