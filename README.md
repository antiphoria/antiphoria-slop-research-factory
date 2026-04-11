# antiphoria-slop-research-factory

## Disclaimer

The software must be used in a **research setting only** and **for artistic purposes**.

## Security guarantee (D-1 §9)

The provenance system proves **process** integrity, not scientific truth. The following is the honest security guarantee from **D-1 §9** (see [`glascannon-ai-draft/d1.md`](glascannon-ai-draft/d1.md)):

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

## Governance

Community rules, licensing split, and communication standards are in the **[D-7 governance charter](glascannon-ai-draft/d7.md)**. Implementers should read **D-7 §16** (invariant checklist) alongside the specs.

## Shiny badges to fill the inner void

[![CI Tests](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-tests.yml/badge.svg)](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-tests.yml)
[![CI Trivy](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-trivy.yml/badge.svg)](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-trivy.yml)
[![CI CodeAudit](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-codeaudit.yml/badge.svg)](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-codeaudit.yml)
[![Gitleaks](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/gitleaks.yml)

## Manual workflow runs

These workflows define **`workflow_dispatch`**, so you can run them without a push:

1. Open **[Actions](https://github.com/antiphoria/antiphoria-slop-research-factory/actions)** for this repository.
2. Select the workflow in the left sidebar (**CI Tests**, **CI Trivy**, **CI CodeAudit**, or **Gitleaks**).
3. Use **Run workflow** (branch dropdown, then the green button).

## Architecture diagrams

Rendered **Mermaid** views (C4-style context, containers, components, trust boundaries) live under [`docs/architecture/`](docs/architecture/README.md). They track the specification drafts in [`glascannon-ai-draft/`](glascannon-ai-draft/).

## License

                Copyright 2026 Georg Popp

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
