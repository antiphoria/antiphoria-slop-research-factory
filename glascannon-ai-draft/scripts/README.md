# Draft tooling

## `spec_ref_audit.py`

Scans `glascannon-ai-draft/d0.md` … `d9.md` for citations of the form `D-<n> §<ref>` and checks that the target file contains a matching heading (`## §N`, `### §N`, `### N.M`, `#### N.M`, or `### 4A`-style).

From the **glascannon-ai-draft** directory:

```bash
python scripts/spec_ref_audit.py
python scripts/spec_ref_audit.py --strict
python scripts/spec_ref_audit.py --markdown scripts/spec-ref-audit-report.md
python scripts/spec_ref_audit.py --json > audit.json
```

`--strict` exits with code 1 if any reference fails to resolve.

Limitations:

- Only `D-0` … `D-9` (single digit).
- Does not validate bare `§8` without a document id, or `Attack N` / `Invariant N` alone.
- Heading heuristics may need extending if you introduce new heading styles.
