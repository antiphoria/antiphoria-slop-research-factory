Pre-Flight Checklist
Almost ready. Here's what to verify before running:

Potential Blockers (check these exist/match)


Concern	What to verify	If missing
workspace.write_output_file(name, content)	Method exists on WorkspaceManager	Add it (3 lines: mkdir + write_text + return path)
workspace.write_state(state)	Method exists	Likely exists (used by all nodes)
workspace.load_state()	Method exists (for resume/CLI)	Needed for resume + status
workspace.relative(abs_path) → str	Returns POSIX relative path	Used in all seal calls
workspace.brief_path	Property returning workspace/brief.json	Used in finalize
workspace.workspace_path / workspace.root	The base path property	Finalize + rescue reference it
HumanRescueRequest.to_dict()	Serialization method	Or use dataclasses.asdict
config_loader.load_config_from_file(path)	Exists, returns FactoryConfig	Only needed if you pass --config
output/ directory	output/__init__.py + output/hai_card_renderer.py created	New package — must exist on disk
ConfidenceTier.from_score()	Classmethod on the enum	Referenced in HAI card renderer
HumanReviewStatus	Enum in types/enums.py	Referenced in HAI card renderer
Minimal Run Setup
1. Install
pip install -e ".[llm]"
2. Environment Variables


export OPENROUTER_API_KEY="sk-or-..."
export GEMINI_API_KEY="..."
3. Sample Brief


{
  "thesis": "Transformer attention mechanisms can be reformulated as a form of differentiable associative memory, providing a unified theoretical framework that connects modern deep learning architectures to classical Hopfield networks.",
  "title_suggestion": "Attention as Associative Memory: A Unifying Framework",
  "field": "Machine Learning / Theoretical Computer Science",
  "target_length_words": 4000,
  "methodology_preferences": ["theoretical analysis", "mathematical proof", "comparative framework"],
  "key_constraints": [
    "Must cite the original Hopfield (1982) and Vaswani et al. (2017) papers",
    "Must provide at least one novel theorem or proposition",
    "Must discuss computational complexity implications"
  ],
  "audience": "ML researchers familiar with transformer architectures"
}
Save as brief.json.
4. Run (no provenance — skip key setup for first test)
slop-factory run --brief brief.json --no-provenance -vv
Or directly:

python -m slop_research_factory.cli run --brief brief.json --no-provenance -vv
5. What to expect on success


workspace/<run_id>/
├── brief.json
├── config.json
├── state.json
├── chain/          ← InMemory seal records
├── output/
│   ├── paper.md
│   ├── hai_card.md
│   ├── manifest.json
│   ├── provenance_report.md
│   └── chain_verification.json
└── steps/          ← intermediate drafts/critiques
Most Likely First Failure
Import error — one of the new modules references something that doesn't exist or is named slightly differently on your actual WorkspaceManager / enums / HumanRescueRequest. Run this first:


python -c "from slop_research_factory.orchestrator import run_factory; print('imports OK')"
If that passes, the run should execute. Share any tracebacks and I'll fix them immediately.