#!/usr/bin/env python3
"""
Mechanical cross-reference audit for glascannon-ai-draft/d0.md … d9.md.

Finds citations of the form  D-<n> §<ref>  (Unicode § U+00A7 or legacy byte 0xA7 in
Latin-1 files) and checks that the target document contains a matching heading.

Usage (from repo root or from glascannon-ai-draft):

  python scripts/spec_ref_audit.py
  python scripts/spec_ref_audit.py --json
  python scripts/spec_ref_audit.py --markdown audit-report.md
  python scripts/spec_ref_audit.py --strict   # exit 1 if any reference fails

Does not validate: "Attack N", "Defense N", "Invariant N" (only the §… segment).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# D-0 §11  |  D-12 §1 (ignored: only d0–d9)  |  optional comma/paren after ref
REF_RE = re.compile(
    r"D-([0-9])\s*(?:\u00a7|§)\s*([0-9]+(?:\.[0-9]+)?|[0-9]+[A-Z])\b",
    re.IGNORECASE,
)


def load_markdown(path: Path) -> str:
    """Decode spec files: UTF-8 (with BOM) first, then strict UTF-8, then Latin-1 (per-byte)."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    return raw.decode("latin-1")


def build_section_index(text: str) -> dict[str, tuple[int, str]]:
    """
    Map logical keys to (line_number, heading_line).

    Keys:
      - "8"     from  ## §8. …  or  ### §8. …
      - "8.4"   from  ### 8.4 …  or  #### 8.4 …
      - "4A"    from  ### 4A. …
    Later headings overwrite earlier same key (last wins); usually unique.
    """
    keys: dict[str, tuple[int, str]] = {}
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        s = line.rstrip()

        m = re.match(r"^##\s+§(\d+)\.\s", s)
        if m:
            keys[m.group(1)] = (i, s.strip())
            continue

        m = re.match(r"^###\s+§(\d+)\.\s", s)
        if m:
            keys[m.group(1)] = (i, s.strip())
            continue

        m = re.match(r"^###\s+(\d+)\.(\d+)\s", s)
        if m:
            keys[f"{m.group(1)}.{m.group(2)}"] = (i, s.strip())
            continue

        m = re.match(r"^####\s+(\d+)\.(\d+)\s", s)
        if m:
            keys[f"{m.group(1)}.{m.group(2)}"] = (i, s.strip())
            continue

        m = re.match(r"^###\s+(\d+)([A-Z])\.\s", s)
        if m:
            keys[f"{m.group(1)}{m.group(2)}"] = (i, s.strip())
            continue

    return keys


def resolve_ref(keys: dict[str, tuple[int, str]], ref: str) -> tuple[bool, str | None]:
    """
    Return (ok, resolved_heading_or_None).

    Rules:
      - Exact match on ref (e.g. 8.4, 4A, 11).
      - For dotted refs, if "8.4" missing but "8" exists, report as partial hint only
        — still FAIL strict audit (sub-section required).
    """
    ref = ref.strip()
    if ref in keys:
        ln, title = keys[ref]
        return True, f"L{ln}: {title}"

    # Parent section only (e.g. cited §8.9 but only §8 exists)
    if "." in ref:
        parent = ref.split(".", 1)[0]
        if parent in keys:
            ln, title = keys[parent]
            return False, f"(parent only L{ln}: {title})"
    return False, None


def iter_source_files(draft_dir: Path) -> list[Path]:
    return sorted(draft_dir.glob("d[0-9].md"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit D-n §… cross-references in d0–d9.")
    parser.add_argument(
        "--draft-dir",
        type=Path,
        default=None,
        help="Directory containing d0.md … d9.md (default: parent of scripts/).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout.")
    parser.add_argument(
        "--markdown",
        type=Path,
        default=None,
        help="Write human-readable Markdown report to this path.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any reference does not resolve.",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    draft_dir = args.draft_dir or (script_dir.parent)
    draft_dir = draft_dir.resolve()

    indices: dict[str, dict[str, tuple[int, str]]] = {}
    for n in range(10):
        p = draft_dir / f"d{n}.md"
        if not p.exists():
            continue
        indices[str(n)] = build_section_index(load_markdown(p))

    findings: list[dict] = []
    by_status: dict[str, list[dict]] = defaultdict(list)

    for src in iter_source_files(draft_dir):
        text = load_markdown(src)
        for m in REF_RE.finditer(text):
            doc_id, ref = m.group(1), m.group(2)
            if doc_id not in indices:
                status = "bad_doc"
                detail = None
            else:
                ok, detail = resolve_ref(indices[doc_id], ref)
                status = "ok" if ok else "missing"

            row = {
                "source_file": src.name,
                "match": m.group(0),
                "target_doc": f"d{doc_id}.md",
                "ref": ref,
                "status": status,
                "resolved": detail,
            }
            findings.append(row)
            by_status[status].append(row)

    # De-duplicate identical (source, target, ref) for cleaner reports
    def dedup_key(r):
        return (r["source_file"], r["target_doc"], r["ref"])

    seen: set[tuple[str, str, str]] = set()
    unique_findings: list[dict] = []
    for r in findings:
        k = dedup_key(r)
        if k in seen:
            continue
        seen.add(k)
        unique_findings.append(r)

    ok_n = sum(1 for r in unique_findings if r["status"] == "ok")
    miss_n = sum(1 for r in unique_findings if r["status"] == "missing")
    bad_n = sum(1 for r in unique_findings if r["status"] == "bad_doc")

    report = {
        "draft_dir": str(draft_dir),
        "unique_references": len(unique_findings),
        "ok": ok_n,
        "missing": miss_n,
        "bad_doc_id": bad_n,
        "findings": sorted(
            unique_findings, key=lambda x: (x["target_doc"], x["ref"], x["source_file"])
        ),
    }

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")

    if args.markdown:
        lines = [
            "# Spec cross-reference audit",
            "",
            f"Draft directory: `{draft_dir}`",
            "",
            f"- Unique `D-n §…` references: **{len(unique_findings)}**",
            f"- Resolved: **{ok_n}**",
            f"- Missing subsection/section: **{miss_n}**",
            f"- Invalid doc id (not 0–9): **{bad_n}**",
            "",
        ]
        if miss_n or bad_n:
            lines.append("## Problems")
            lines.append("")
            lines.append("| Source | Citation | Target | Status | Detail |")
            lines.append("|--------|----------|--------|--------|--------|")
            for r in report["findings"]:
                if r["status"] != "ok":
                    det = (r.get("resolved") or "").replace("|", "\\|")
                    lines.append(
                        f"| {r['source_file']} | `{r['match']}` | {r['target_doc']} | {r['status']} | {det} |"
                    )
            lines.append("")
        lines.append("## All references (deduplicated)")
        lines.append("")
        lines.append("| Source | Citation | Target | Resolved heading |")
        lines.append("|--------|----------|--------|------------------|")
        for r in report["findings"]:
            st = "✅" if r["status"] == "ok" else "❌"
            det = (r.get("resolved") or "—").replace("|", "\\|")
            lines.append(
                f"| {r['source_file']} | `{r['match']}` | {r['target_doc']} | {st} {det} |"
            )
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not args.json:
        print(f"Draft dir: {draft_dir}")
        print(f"Unique D-n § references: {len(unique_findings)}")
        print(f"  OK:      {ok_n}")
        print(f"  MISSING: {miss_n}")
        print(f"  BAD_DOC: {bad_n}")
        if miss_n or bad_n:
            print("\n--- Issues ---")
            for r in report["findings"]:
                if r["status"] != "ok":
                    print(
                        f"  {r['source_file']}: {r['match']} -> {r['target_doc']} [{r['status']}] {r.get('resolved') or ''}"
                    )

    if args.strict and (miss_n or bad_n):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
