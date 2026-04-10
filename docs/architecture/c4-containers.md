# C4 Level 2 — Containers and deployment

**Aligned with:** D-0 §7 (execution model), §10.1 (Phase 1 vs Phase 2 baseline); D-9 §2 (deployment tiers), §9 (Docker Compose).

## Tier 1 — single Python process (default)

Phase 1: one **factory process** (**LangGraph** orchestrator, nodes, LLM client, seal wrapper), **workspace** on local disk, and **slop-cli** as a separate binary on the host invoked by the factory. No Redis or queue required (D-9 §2, D-0 §10.1).

```mermaid
flowchart TB
  subgraph host [Host_Tier_1]
    PyProc[Factory_Python_process]
    WS[(workspaces_directory)]
    PyProc -->|"read_write"| WS
  end
  SealBin[slop_cli_binary_PATH]
  PyProc -->|"spawn"| SealBin
  PyProc --> Net[Internet_LLM_and_tool_APIs]
```

## Tier 2 — Docker (Phase 1 shape)

Single **application container** plus a **host-mounted volume** for workspaces (D-9 §9.1).

```mermaid
flowchart TB
  subgraph dockerHost [Host_machine]
    subgraph ctr [antiphoria_factory_container]
      App[Python_app_slop_cli_inside_image]
    end
    Vol[(Host_volume_workspaces)]
    App -->|"bind_mount"| Vol
  end
  App --> Net2[External_APIs]
```

## Tier 2 — optional Phase 2 queue topology

**v0.2+ when justified:** Redis, optional dashboard, **worker** consuming ARQ jobs — still writing workspaces via a shared volume (D-9 §9.1 Phase 2 ASCII).

```mermaid
flowchart TB
  subgraph compose [Docker_Compose_Phase_2_optional]
    Redis[redis_job_queue]
    Dash[antiphoria_dashboard_Streamlit_optional]
    Worker[antiphoria_worker_ARQ_factory]
    Redis --> Worker
    Dash -.->|"observability"| Worker
    SharedVol[(Shared_workspace_volume)]
    Worker --> SharedVol
  end
  Worker --> Net3[LLM_and_tool_APIs]
```

## Five logical layers (mapping)

D-0 §2.1 stacks **orchestration**, **inference middleware**, **Aletheia loop**, **provenance engine**, and **output artifacts** inside the **Factory Python process** boundary above; **slop-cli** realizes Layer 4’s cryptographic operations at process boundary. See [c4-components.md](c4-components.md) for package-level breakdown.
