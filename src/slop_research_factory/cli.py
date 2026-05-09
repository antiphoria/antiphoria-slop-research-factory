# cli.py
# src/slop_research_factory/cli.py

"""
Command-line interface for the SLOP Research Factory.

Entry point: ``slop-factory`` (registered via pyproject.toml console_scripts).

Subcommands:
    run      Execute a new research pipeline from a brief.
    resume   Resume a paused or crashed run.
    verify   Verify a workspace's provenance chain integrity.
    status   Print current state summary of a workspace.

Usage examples:

.. code-block:: bash

    # Basic run
    slop-factory run --brief brief.json

    # With explicit config and run ID
    slop-factory run --brief brief.json --config antiphoria.toml --run-id my-run-001

    # Resume a crashed run
    slop-factory resume --workspace ./workspace/abc123

    # Verify chain integrity
    slop-factory verify --workspace ./workspace/abc123

    # Check run status
    slop-factory status --workspace ./workspace/abc123

Spec references:
    D-0 §13   Implementation step plan — CLI phase.
    D-2 §3    Run lifecycle.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import NoReturn

__all__ = ["main"]


# ── Logging setup ────────────────────────────────────────────────────


def _configure_logging(verbosity: int) -> None:
    """Configure root logger based on -v/-vv flags."""
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


# ── Argument parsing ─────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slop-factory",
        description="SLOP Research Factory — AI-powered research pipeline with provenance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  slop-factory run --brief brief.json\n"
            "  slop-factory run --brief brief.json --config antiphoria.toml --run-id my-run\n"
            "  slop-factory resume --workspace ./workspace/abc123\n"
            "  slop-factory verify --workspace ./workspace/abc123\n"
            "  slop-factory status --workspace ./workspace/abc123\n"
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v info, -vv debug).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── run ───────────────────────────────────────────────────────
    run_parser = subparsers.add_parser(
        "run",
        help="Execute a new research pipeline from a brief.",
    )
    run_parser.add_argument(
        "--brief",
        type=Path,
        required=True,
        help="Path to research brief JSON file.",
    )
    run_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to antiphoria.toml configuration file (optional).",
    )
    run_parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Explicit run identifier (auto-generated UUID4 if omitted).",
    )
    run_parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("./workspace"),
        help="Parent directory for run workspaces (default: ./workspace).",
    )
    run_parser.add_argument(
        "--no-provenance",
        action="store_true",
        default=False,
        help="Disable cryptographic provenance (use InMemory engine).",
    )

    # ── resume ────────────────────────────────────────────────────
    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume a paused or crashed run.",
    )
    resume_parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Path to existing run workspace directory.",
    )
    resume_parser.add_argument(
        "--response",
        type=Path,
        default=None,
        help="Path to human response JSON (for AWAITING_HUMAN runs).",
    )

    # ── verify ────────────────────────────────────────────────────
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify a workspace's provenance chain integrity.",
    )
    verify_parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Path to run workspace directory.",
    )
    verify_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="output_json",
        help="Output verification report as JSON instead of human-readable.",
    )

    # ── status ────────────────────────────────────────────────────
    status_parser = subparsers.add_parser(
        "status",
        help="Print current state summary of a workspace.",
    )
    status_parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Path to run workspace directory.",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="output_json",
        help="Output status as JSON instead of human-readable.",
    )

    return parser


# ── Subcommand handlers ──────────────────────────────────────────────


async def _cmd_run(args: argparse.Namespace) -> int:
    """Handle ``slop-factory run``."""
    from slop_research_factory.config import FactoryConfig
    from slop_research_factory.config_loader import load_config_from_file
    from slop_research_factory.orchestrator import run_factory

    # Load brief
    brief_path: Path = args.brief
    if not brief_path.exists():
        _err(f"Brief file not found: {brief_path}")
        return 1

    try:
        brief_data = json.loads(brief_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _err(f"Failed to read brief: {exc}")
        return 1

    if not isinstance(brief_data, dict):
        _err("Brief must be a JSON object (dict)")
        return 1

    # Load config
    config: FactoryConfig | None = None
    config_path: Path | None = args.config

    if config_path is not None:
        if not config_path.exists():
            _err(f"Config file not found: {config_path}")
            return 1
        try:
            config = load_config_from_file(config_path)
        except Exception as exc:
            _err(f"Failed to load config: {exc}")
            return 1

    if config is None:
        config = FactoryConfig()

    # Apply CLI override for provenance
    if args.no_provenance:
        # Mutate config to disable provenance
        import dataclasses

        config = dataclasses.replace(config, enable_provenance=False)

    # Run
    _out(f"Starting factory run…")
    _out(f"  Brief: {brief_path}")
    if config_path:
        _out(f"  Config: {config_path}")
    _out(f"  Workspace root: {args.workspace_root}")
    if args.run_id:
        _out(f"  Run ID: {args.run_id}")
    _out("")

    try:
        result = await run_factory(
            brief=brief_data,
            config=config,
            run_id=args.run_id,
            workspace_root=args.workspace_root,
        )
    except Exception as exc:
        _err(f"Factory run failed: {exc}")
        logging.getLogger(__name__).debug("Traceback:", exc_info=True)
        return 1

    # Report outcome
    _out("")
    _out("=" * 60)
    _out(f"  {result.summary()}")
    _out(f"  Workspace: {result.workspace_path}")
    _out("=" * 60)

    if result.success:
        _out("\n✅ Run completed successfully.")
        _out(f"   Output: {result.workspace_path / 'output' / 'paper.md'}")
        return 0
    elif result.state.status.value == "AWAITING_HUMAN":
        _out("\n⏸️  Run paused — human intervention required.")
        _out(f"   Inspect: {result.workspace_path / 'rescue' / 'request.json'}")
        _out("   Resume:  slop-factory resume --workspace " f"{result.workspace_path}")
        return 2
    else:
        _err(f"\n❌ Run ended with status: {result.state.status.value}")
        return 1


async def _cmd_resume(args: argparse.Namespace) -> int:
    """Handle ``slop-factory resume``."""
    from slop_research_factory.orchestrator import resume_factory

    workspace_path: Path = args.workspace
    if not workspace_path.exists():
        _err(f"Workspace not found: {workspace_path}")
        return 1

    # Load optional human response
    human_response: dict | None = None
    if args.response:
        response_path: Path = args.response
        if not response_path.exists():
            _err(f"Response file not found: {response_path}")
            return 1
        try:
            human_response = json.loads(response_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _err(f"Failed to read response: {exc}")
            return 1

    _out(f"Resuming run from: {workspace_path}")
    _out("")

    try:
        result = await resume_factory(
            workspace_path=workspace_path,
            human_response=human_response,
        )
    except ValueError as exc:
        _err(f"Cannot resume: {exc}")
        return 1
    except Exception as exc:
        _err(f"Resume failed: {exc}")
        logging.getLogger(__name__).debug("Traceback:", exc_info=True)
        return 1

    # Report outcome
    _out("")
    _out("=" * 60)
    _out(f"  {result.summary()}")
    _out("=" * 60)

    if result.success:
        _out("\n✅ Run completed successfully.")
        return 0
    elif result.state.status.value == "AWAITING_HUMAN":
        _out("\n⏸️  Run still paused — further intervention needed.")
        return 2
    else:
        _err(f"\n❌ Run ended with status: {result.state.status.value}")
        return 1


async def _cmd_verify(args: argparse.Namespace) -> int:
    """Handle ``slop-factory verify``."""
    from slop_research_factory.seal.sdk_adapter import create_seal_engine
    from slop_research_factory.workspace.manager import WorkspaceManager

    workspace_path: Path = args.workspace
    if not workspace_path.exists():
        _err(f"Workspace not found: {workspace_path}")
        return 1

    workspace = WorkspaceManager(workspace_path)

    try:
        state = workspace.load_state()
    except Exception as exc:
        _err(f"Failed to load state: {exc}")
        return 1

    _out(f"Verifying chain for run: {state.run_id}")
    _out(f"  Status: {state.status.value}")
    _out(f"  Steps:  {state.step_index + 1}")
    _out("")

    # Construct engine in verify-only mode
    try:
        engine = create_seal_engine(
            workspace=workspace_path,
            run_id=state.run_id,
            enable_provenance=state.config.enable_provenance,
            resume=True,
        )
    except RuntimeError as exc:
        _err(f"Cannot initialize seal engine: {exc}")
        return 1

    # Run verification
    try:
        report = await engine.verify_chain()
    except Exception as exc:
        _err(f"Verification failed: {exc}")
        return 1

    # Output
    if args.output_json:
        output = {
            "run_id": report.run_id,
            "chain_intact": report.chain_intact,
            "total_steps": report.total_steps,
            "first_error_index": report.first_error_index,
            "steps": [
                {
                    "step_index": s.step_index,
                    "step_type": s.step_type,
                    "ok": s.ok,
                    "errors": s.errors,
                }
                for s in report.steps
            ],
        }
        _out(json.dumps(output, indent=2))
    else:
        _render_verification_report(report)

    return 0 if report.chain_intact else 1


async def _cmd_status(args: argparse.Namespace) -> int:
    """Handle ``slop-factory status``."""
    from slop_research_factory.workspace.manager import WorkspaceManager

    workspace_path: Path = args.workspace
    if not workspace_path.exists():
        _err(f"Workspace not found: {workspace_path}")
        return 1

    workspace = WorkspaceManager(workspace_path)

    try:
        state = workspace.load_state()
    except Exception as exc:
        _err(f"Failed to load state: {exc}")
        return 1

    if args.output_json:
        _render_status_json(state)
    else:
        _render_status_human(state, workspace_path)

    return 0


# ── Output rendering ─────────────────────────────────────────────────


def _render_verification_report(report) -> None:
    """Print human-readable verification report."""
    integrity = "✅ INTACT" if report.chain_intact else "❌ BROKEN"

    _out(f"Chain Integrity: {integrity}")
    _out(f"Total Steps:     {report.total_steps}")
    if report.first_error_index is not None:
        _out(f"First Error:     step {report.first_error_index}")
    _out("")

    _out(f"{'Step':<6} {'Type':<20} {'Status':<8} {'Errors'}")
    _out(f"{'─'*6} {'─'*20} {'─'*8} {'─'*40}")

    for s in report.steps:
        status = "✅" if s.ok else "❌"
        errors = "; ".join(s.errors) if s.errors else "—"
        _out(f"{s.step_index:<6} {s.step_type:<20} {status:<8} {errors}")

    _out("")
    if report.chain_intact:
        _out("All steps verified — provenance chain is intact.")
    else:
        _out("⚠️  Chain integrity failure detected. See errors above.")


def _render_status_human(state, workspace_path: Path) -> None:
    """Print human-readable status summary."""
    _out("┌─────────────────────────────────────────────────────────┐")
    _out("│           SLOP Research Factory — Run Status            │")
    _out("├─────────────────────────────────────────────────────────┤")
    _out(f"│  Run ID:      {state.run_id:<41} │")
    _out(f"│  Status:      {state.status.value:<41} │")
    _out(f"│  Workspace:   {str(workspace_path):<41} │")
    _out("├─────────────────────────────────────────────────────────┤")
    _out(f"│  Cycles:      {state.cycle_count:<41} │")
    _out(f"│  Rejections:  {state.rejection_count:<41} │")
    _out(f"│  Revisions:   {state.revision_count:<41} │")
    _out(f"│  Step Index:  {state.step_index:<41} │")
    _out("├─────────────────────────────────────────────────────────┤")

    cost_str = f"${state.total_estimated_cost_usd:.4f}"
    tokens_str = f"{state.total_input_tokens + state.total_output_tokens:,}"
    time_str = f"{state.total_wall_clock_seconds:.1f}s"

    _out(f"│  Tokens:      {tokens_str:<41} │")
    _out(f"│  Est. Cost:   {cost_str:<41} │")
    _out(f"│  Wall Clock:  {time_str:<41} │")
    _out("├─────────────────────────────────────────────────────────┤")
    _out(f"│  Created:     {state.created_at:<41} │")
    _out(f"│  Updated:     {state.updated_at:<41} │")

    if state.latest_hash:
        hash_display = f"{state.latest_hash[:16]}…"
    else:
        hash_display = "—"
    _out(f"│  Latest Hash: {hash_display:<41} │")
    _out("└─────────────────────────────────────────────────────────┘")

    # Brief summary
    brief_title = (
        state.brief.get("title_suggestion")
        or state.brief.get("thesis", "—")[:60]
    )
    _out(f"\n  Brief: {brief_title}")

    # Verdict (if available)
    critique = state.current_critique or {}
    verdict = critique.get("effective_verdict") or critique.get("verdict")
    if verdict:
        _out(f"  Last Verdict: {verdict}")


def _render_status_json(state) -> None:
    """Print machine-readable status as JSON."""
    output = {
        "run_id": state.run_id,
        "status": state.status.value,
        "cycle_count": state.cycle_count,
        "rejection_count": state.rejection_count,
        "revision_count": state.revision_count,
        "step_index": state.step_index,
        "latest_hash": state.latest_hash,
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "total_think_tokens": state.total_think_tokens,
        "total_estimated_cost_usd": state.total_estimated_cost_usd,
        "total_wall_clock_seconds": state.total_wall_clock_seconds,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "brief_title": (
            state.brief.get("title_suggestion")
            or state.brief.get("thesis", "")[:80]
        ),
    }
    _out(json.dumps(output, indent=2))


# ── I/O helpers ──────────────────────────────────────────────────────


def _out(msg: str) -> None:
    """Print to stdout."""
    print(msg, file=sys.stdout)


def _err(msg: str) -> None:
    """Print to stderr."""
    print(f"ERROR: {msg}", file=sys.stderr)


# ── Entry point ──────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> NoReturn:
    """CLI entry point — parse args and dispatch to subcommand.

    Exit codes:
        0 — Success (run completed, chain intact, status OK).
        1 — Error (run failed, chain broken, invalid args).
        2 — Paused (run awaiting human intervention).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    if args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(1)

    # Dispatch
    handler_map = {
        "run": _cmd_run,
        "resume": _cmd_resume,
        "verify": _cmd_verify,
        "status": _cmd_status,
    }

    handler = handler_map.get(args.command)
    if handler is None:
        _err(f"Unknown command: {args.command}")
        sys.exit(1)

    # Run async handler
    try:
        exit_code = asyncio.run(handler(args))
    except KeyboardInterrupt:
        _err("\nInterrupted by user")
        sys.exit(130)
    except Exception as exc:
        _err(f"Unexpected error: {exc}")
        logging.getLogger(__name__).debug("Traceback:", exc_info=True)
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()