# Architecture diagrams (C4-style)

Mermaid diagrams derived from the specification suite in [`glascannon-ai-draft/`](../../glascannon-ai-draft/). The numbered documents (D-0, D-1, D-9, …) remain the **source of truth**; these pages are for **rendered** views (GitHub, Cursor, and other Markdown previews).

## Index

| Document | View | Primary spec anchors |
|----------|------|----------------------|
| [c4-context.md](c4-context.md) | System context (C4 L1) | D-0 §1–§2, D-1 §4 (trust framing) |
| [c4-containers.md](c4-containers.md) | Containers / deployment (C4 L2) | D-0 §7, §10.1, D-9 §2, §9 |
| [c4-components.md](c4-components.md) | Major packages (C4 L3) | D-9 §3, D-0 §2.1 |
| [trust-boundaries.md](trust-boundaries.md) | TB1–TB4 | D-1 §4 |

## When to update

After edits to **D-0 §2**, **D-1 §4**, or **D-9 §3 / §9**, reconcile the corresponding diagram and adjust this README if the mapping changes.

**Last aligned with spec:** treat as “HEAD of `glascannon-ai-draft/`” at diagram change time (no separate date field to avoid staleness).

## Related

- ASCII diagrams in [glascannon-ai-draft/d0.md](../../glascannon-ai-draft/d0.md) (§2) and [glascannon-ai-draft/d1.md](../../glascannon-ai-draft/d1.md) (§4) are intentionally **not removed**; they stay authoritative for fine-grained layout.
