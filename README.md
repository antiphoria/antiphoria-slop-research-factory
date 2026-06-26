# antiphoria-slop-research-factory

## A human note
```text
There is so much going on here that I genuinely have no idea about it.

- it's "spec-driven" which I'll never do again
- it's all over the place: spaghetti code, loose-ends, unfinished routes
- [...]

Do not mistake this for a solid piece of software. It's a vibe-coded mess.

Yet, I absolutely did as best as I could within the given timeframe for hobby-projects.

Moreover, this is heavily leaning into the exploration of all these AI-era promises.

I recently heard something along the lines of:
> "coding is solved"

Is that so?

If reading AI code is not a blocker to you - be warned but ofc go ahead and explore it.
```

For development and coding assistants, see **[AGENTS.md](AGENTS.md)**.

## Disclaimer (for real)

The software must be used in a **research setting only** and **for artistic purposes**.

## Security notice

The provenance system is supposed to prove **process** integrity, not scientific truth.

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

## Shiny badges to fill the inner void

[![CI Lint](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-lint.yml/badge.svg)](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-lint.yml)
[![CI Tests](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-tests.yml/badge.svg)](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-tests.yml)
[![CI Trivy](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-trivy.yml/badge.svg)](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/ci-trivy.yml)
[![Gitleaks](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/antiphoria/antiphoria-slop-research-factory/actions/workflows/gitleaks.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/antiphoria/antiphoria-slop-research-factory/badge)](https://securityscorecards.dev/viewer/?uri=github.com/antiphoria/antiphoria-slop-research-factory)

## Manual workflow runs

These workflows define **`workflow_dispatch`**, so you can run them without a push:

1. Open **[Actions](https://github.com/antiphoria/antiphoria-slop-research-factory/actions)** for this repository.
2. Select the workflow in the left sidebar (**CI Lint**, **CI Tests**, **CI Trivy**, **Gitleaks**, or **Org Quality (OpenSSF Scorecard)**).
3. Use **Run workflow** (branch dropdown, then the green button).

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
