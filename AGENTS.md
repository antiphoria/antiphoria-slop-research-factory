# AGENTS.md — coding assistant guide

This file is the **only** operational doc for coding assistants working in this repo.
Humans read [README.md](README.md) for framing; you read this for how the code actually works.

## Authority

**If this file disagrees with code or tests, code and tests win.** Update AGENTS.md to match.

This is a hobby prototype — spaghetti code, loose ends, unfinished routes. Do not treat it as production software.
Do not invent features from old spec documents; they were removed. Recover archaeology only via git tag `spec-era-v0.1` if needed.

Use in **research settings** and **for artistic purposes** only (Apache 2.0).

---

## Architecture

Generator → Verifier → Reviser loop, orchestrated with LangGraph:

```
genesis (orchestrator)
    │
    ▼
GENERATOR ──► VERIFIER ──┬── CORRECT  ──► FINALIZE
                         ├── FIXABLE  ──► REVISER ──► VERIFIER (loop)
                         ├── WRONG    ──► REVISER ──► VERIFIER (loop)
                         └── caps hit ──► HUMAN_RESCUE (halt)
```

Routing logic lives in `src/slop_research_factory/engine/routing.py` — single source of truth for verdict → next node.

- **Demotion:** `CORRECT` with confidence below `verifier_confidence_threshold` becomes effective `FIXABLE`.
- **FIXABLE** → reviser in `targeted_repair` mode.
- **WRONG** → reviser in `full_rewrite` mode.
- Loop/budget caps → `human_rescue_queue`.

Graph wiring: `src/slop_research_factory/engine/graph.py`.
Run lifecycle: `src/slop_research_factory/orchestrator.py`.

Each pipeline node follows a four-phase pattern: PRE seal → inference/tools → POST seal → state update.

---

## Module map

| Path | Responsibility |
|------|----------------|
| `cli.py` | CLI entry (`slop-factory`) |
| `orchestrator.py` | Run/resume lifecycle, workspace bootstrap, genesis seal |
| `config.py`, `config_loader.py` | `FactoryConfig`, TOML loader |
| `engine/graph.py` | LangGraph compile + invoke |
| `engine/routing.py` | Verdict routing (pure logic, no I/O) |
| `nodes/*` | generator, verifier, reviser, finalize, human_rescue |
| `llm/` | LiteLLM client, think parsing, Instructor structured output |
| `seal/` | InMemory engine, SDK adapter, `seal_step`, metadata registry |
| `tools/` | Citation check protocol + **canned** client only |
| `citations/` | Regex citation extractor |
| `prompts/` | `*.txt` templates + `*_prompt.py` loaders |
| `types/` | State, brief, enums, verifier output, HAI card, provenance |
| `workspace/manager.py` | Disk layout, atomic `state.json` I/O |
| `output/hai_card_renderer.py` | HAI card markdown |

Sibling repo for cryptographic sealing: `../antiphoria-slop-provenance` (optional `[provenance]` extra).

---

## Implemented vs not

### Works today

- CLI: `slop-factory run|resume|verify|status`
- LangGraph G→V→R pipeline with conditional routing
- Local workspace under `workspace/<run_id>/`
- LiteLLM inference + Instructor structured verifier output
- Sealing: `InMemorySealEngine` (dev) or `SDKSealEngine` when `enable_provenance=true` + keys installed
- Canned Crossref / Semantic Scholar responses (`tools/canned.py`)
- Regex citation extraction
- Terminal artifacts: `paper.md`, `hai_card.md`, `manifest.json`, optional provenance report
- Human rescue via files: `rescue/request.json` + manual `response.json`

### Do not implement unless explicitly asked

- Docker, docker-compose, ARQ, Redis, Streamlit (`pyproject.toml` `[production]` deps are declared only)
- Real HTTP tool clients (Crossref/S2/Tavily live APIs)
- Tavily integration (`enable_tavily_search` config flag exists; verifier never calls it)
- `citations/extractor.py` with `mode="llm"` (raises `NotImplementedError`)
- Verifier Phase 1 deterministic pre-checks (skipped in current code)
- HAI Card T1 deterministic checks in finalize (hardcoded 0/0)
- `CheckpointBackend.POSTGRES` (enum only; persistence is local `state.json`)
- Mid-graph resume (resume always re-enters graph at GENERATOR)
- `slop-cli` subprocess wrapper (sealing is Python SDK or in-memory)
- CLI subcommands `doctor`, `inspect`

---

## Security guarantee

The provenance system proves **process** integrity, not scientific truth.

> **Given an unmodified factory installation, an honest operator, and collision-resistant hash functions:**
>
> The provenance manifest cryptographically proves that the output artifact was produced by a specific, ordered sequence of LLM inference calls and tool invocations, that no steps in this sequence were added, removed, or reordered after sealing, and that the output artifact has not been modified since the final seal.
>
> **The manifest does NOT prove:**
>
> - That the sealed content is scientifically correct
> - That the sealed content was actually produced by an LLM (vs. human-authored)
> - That the claimed model identities are accurate
> - That all runs performed by the operator have been disclosed
> - That the Verifier's approval reflects genuine quality

---

## Dev workflow

```bash
# From repo root
uv sync --extra dev --extra provenance   # provenance optional for most tests
pytest
ruff check src tests
mypy src
```

Copy `.env.example` → `.env` and set API keys. `slop-factory` loads `.env` from the current working directory.

### CLI examples

```bash
slop-factory run --brief brief.json
slop-factory run --brief brief.json --config antiphoria.toml --run-id my-run-001
slop-factory resume --workspace ./workspace/abc123
slop-factory verify --workspace ./workspace/abc123
slop-factory status --workspace ./workspace/abc123
```

### Config

- `FactoryConfig` in `config.py`; load via TOML (`config_loader.py`).
- Provenance requires hybrid signing keys (file paths or `ANTIPHORIA_*_KEY_B64` env vars). See `.env.example` and sibling `antiphoria-slop-provenance` SDK docs.

### Disable provenance (deliberately verbose)

Both are required:

1. `[provenance] enabled = false` in `antiphoria.toml`
2. `ANTIPHORIA_I_UNDERSTAND_NO_PROVENANCE=true` in environment

Silent one-click disable is intentionally forbidden.

---

## Prompt editing

Prompts live in `src/slop_research_factory/prompts/` as versioned `*.txt` files, loaded by `generator_prompt.py`, `verifier_prompt.py`, `reviser_prompt.py`.

Procedure:

1. Edit the relevant `.txt` file.
2. Run prompt unit tests: `pytest tests/unit/test_*_prompt.py`
3. Note the change briefly in the **Prompt changelog** section below.

### Prompt changelog

- **v0.1 (2026-04-15):** Initial prompts for generator, verifier, reviser, citation extractor.

---

## Sealing notes

- One seal engine per `(workspace, run_id)`.
- Raw LLM API response bytes are sealed **before** structured parsing (verifier uses Instructor).
- Content paths must be relative, POSIX-safe, under the workspace.
- Cross-process: use `SealEngine.resume(...)` after peer writes; in-memory `latest_hash` goes stale.
- SDK bridge: `seal/sdk_adapter.py` wraps `antiphoria_sdk`; see sibling provenance repo for key material.

---

## Testing expectations

| Area | Canonical tests |
|------|-----------------|
| Verdict routing | `tests/unit/test_routing.py` |
| Full mocked pipeline | `tests/integration/test_graph.py` |
| Per-node contracts | `tests/integration/test_*_node.py` |
| Seal chain | `tests/unit/test_seal_step.py`, `test_provenance.py`, `test_seal_engine_in_memory.py` |

Integration tests use **mocked LLM and canned tools** — they do not prove live API behavior.

**Weak / missing coverage:** orchestrator resume happy path after human rescue, end-to-end live LLM smoke, Docker/production stack.

Test IDs like `E1-R01` in routing tests encode behavior; they are not external spec references.

---

## Governance essentials

- Project name includes **slop** (`antiphoria-slop-research-factory`).
- License: Apache 2.0.
- Output artifacts must not be presented as human-verified research without disclosure.
