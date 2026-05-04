#!/usr/bin/env python3
"""ALARMv3 end-to-end demo run: discovery → analysis → deep synthesis → implementation.

Drives the full pipeline by importing core modules directly (no MCP layer).
Resumable: re-running from any state continues from the last successful phase.

Usage:
    python scripts/demo_full_run.py --source /path/to/legacy --workspace /path/to/workspace --target /path/to/working_copy

Defaults assume the ADDS demo:
    --source /workspaces/ADDS
    --workspace /workspaces/ADDS_ALARMv3
    --target /workspaces/ADDS_modernized_run2
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

import yaml


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def check_prereqs() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3):
            pass
        log("Ollama reachable on :11434")
    except Exception as e:
        log(f"WARNING: Ollama not reachable ({e}) — Phase 2 RAG will be skipped")


def ensure_autopilot(alarm_dir: Path) -> None:
    policy_path = alarm_dir / "policy" / "autopilot.yaml"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy = {
        "enabled": True,
        "rules": [
            {"category": cat, "max_risk_level": 3, "max_effort": "L",
             "description": f"Auto-accept low-to-mid risk {cat} changes"}
            for cat in ("security", "modernization", "quality", "dependency",
                        "architecture", "performance")
        ],
    }
    policy_path.write_text(yaml.dump(policy, sort_keys=False))
    log(f"Autopilot policy: enabled, {len(policy['rules'])} rules")


def poll_job(orch, job_id: str, label: str, timeout_s: int = 7200) -> dict:
    start = time.time()
    last_pct = -1
    while True:
        status = orch.get_job_status(job_id)
        s = status.get("status", "unknown")
        pct = status.get("progress")
        msg = status.get("status_message", "")
        if pct is not None and pct != last_pct:
            log(f"  {label}: {pct}% — {msg}")
            last_pct = pct
        if s == "complete":
            log(f"{label} complete ({int(time.time() - start)}s)")
            return status
        if s == "failed":
            sys.exit(f"{label} FAILED: {status.get('error', 'unknown')}")
        if time.time() - start > timeout_s:
            sys.exit(f"{label} timed out after {timeout_s}s")
        time.sleep(5)


def auto_accept_all_recommendations(session) -> int:
    """Auto-accept only recommendations the adversarial evaluator marked 'accept'.

    Recommendations with evaluator_verdict in {'pending','revise','reject'} are
    left untouched and require human review via the MCP tool. This is the safe
    default for non-interactive runs; see post-mortem §11 for context.
    """
    db_path = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "UPDATE recommendation SET review_status='accepted', approved=1 "
        "WHERE session_id=? AND evaluator_verdict='accept'",
        (session.session_id,),
    )
    n = conn.execute(
        "SELECT COUNT(*) FROM recommendation WHERE session_id=? AND approved=1",
        (session.session_id,),
    ).fetchone()[0]
    conn.commit()
    conn.close()
    return n


def get_recommendation_ranks(session) -> list[int]:
    db_path = session.artifact_dir / "analysis.db"
    conn = sqlite3.connect(db_path, timeout=10)
    rows = conn.execute(
        "SELECT rank FROM recommendation WHERE session_id=? AND approved=1 ORDER BY rank",
        (session.session_id,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="/workspaces/ADDS")
    parser.add_argument("--workspace", default="/workspaces/ADDS_ALARMv3")
    parser.add_argument("--target", default="/workspaces/ADDS_modernized_run2")
    parser.add_argument("--max-subsystems", type=int, default=15)
    parser.add_argument("--max-concurrent", type=int, default=3)
    parser.add_argument("--skip-rag", action="store_true",
                        help="Skip Phase 2 RAG embedding build")
    parser.add_argument("--skip-implementation", action="store_true",
                        help="Stop after recommendations are written")
    args = parser.parse_args()

    log(f"Source     : {args.source}")
    log(f"Workspace  : {args.workspace}")
    log(f"Target     : {args.target}")

    check_prereqs()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from alarmv3.core.guardrails import SessionState
    from alarmv3.core.orchestration import Orchestrator
    from alarmv3.core.session import SessionManager

    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    sm = SessionManager(workspace)
    session = sm.get_or_create()
    log(f"Session    : {session.session_id} (state={session.state.value})")

    orch = Orchestrator(session)

    # ── Phase 0: attach + confirm ─────────────────────────────────────────
    if session.state == SessionState.UNATTACHED:
        session.set_source(Path(args.source).resolve())
        session.transition_to(SessionState.ATTACHED)
        log("Attached source")
    if session.state == SessionState.ATTACHED:
        session.transition_to(SessionState.READ_ONLY_CONFIRMED)
        log("Read-only guardrails confirmed")

    # ── Phase 1: discovery ────────────────────────────────────────────────
    if session.state == SessionState.READ_ONLY_CONFIRMED:
        session.transition_to(SessionState.ANALYSIS_IN_PROGRESS)
        log("Starting file discovery...")
        job = orch.start_mapping()
        result = poll_job(orch, job, "Discovery")
        log(f"  Discovered {result.get('files_discovered', '?')} files")

    # ── Phase 7: language research (uses cached grammars from memory.db) ─
    if session.state == SessionState.ANALYSIS_IN_PROGRESS:
        log("Starting language research (Phase 7)...")
        job = orch.start_language_research(max_samples_per_language=5,
                                           persist_on_success=True)
        poll_job(orch, job, "Language research")

    # ── Phase 1 cont'd: tree-sitter analysis ──────────────────────────────
    if session.state == SessionState.ANALYSIS_IN_PROGRESS:
        log("Starting tree-sitter analysis...")
        job = orch.start_analysis()
        poll_job(orch, job, "Analysis")

    # ── Phase 2: RAG embeddings (Ollama) ──────────────────────────────────
    if session.state == SessionState.ANALYSIS_IN_PROGRESS and not args.skip_rag:
        log("Building RAG vector index (Ollama nomic-embed-text)...")
        try:
            from alarmv3.core.knowledge import KnowledgeBuilder
            stats = KnowledgeBuilder(session).build()
            log(f"  Embedded {stats.get('chunks_embedded', '?')} chunks")
        except Exception as e:
            log(f"  RAG build failed: {e} — continuing without vector index")

    # ── Phase 6: deep analysis (multi-pass synthesis + adversarial eval) ─
    if session.state == SessionState.ANALYSIS_IN_PROGRESS:
        log(f"Starting deep analysis (max_subsystems={args.max_subsystems})...")
        log("  This is the main Claude API spend — typically 15-30 min.")
        job = orch.start_deep_analysis(
            max_subsystems=args.max_subsystems,
            cyclomatic_threshold=10,
            coupling_threshold=10,
            aaa_grounding=None,
        )
        result = poll_job(orch, job, "Deep analysis", timeout_s=10800)
        log(f"  Generated {result.get('recommendation_count', '?')} recommendations")
        log(f"  Coverage: {result.get('coverage_pct', '?')}%")
        # The MCP tool wrapper does this transition, but we call orchestration
        # directly here, so we have to do it ourselves.
        if session.state == SessionState.ANALYSIS_IN_PROGRESS:
            session.transition_to(SessionState.RECOMMENDATIONS_PENDING_REVIEW)

    # ── Phase 3 review gate (auto-accept all in non-interactive run) ─────
    if session.state == SessionState.RECOMMENDATIONS_PENDING_REVIEW:
        n = auto_accept_all_recommendations(session)
        session.transition_to(SessionState.ANALYSIS_COMPLETE)
        log(f"Auto-accepted {n} recommendations (non-interactive run)")

    if args.skip_implementation:
        log("Stopping before implementation (--skip-implementation set)")
        log("Artifacts available at: " + str(session.artifact_dir))
        return

    # ── Phase 4 prep: implementation plan ────────────────────────────────
    if session.state == SessionState.ANALYSIS_COMPLETE:
        ranks = get_recommendation_ranks(session)
        if not ranks:
            sys.exit("No accepted recommendations to implement")
        log(f"Creating implementation plan for {len(ranks)} items...")
        from alarmv3.core.implementation import (ImplementationPlanner,
                                                  clone_source_to_target)
        plan = ImplementationPlanner(session).create_plan(ranks)
        session.transition_to(SessionState.IMPLEMENTATION_PLANNED)
        log(f"  Plan created: {plan.get('plan_item_count', '?')} items")

    # ── Phase 4: clone source to target working dir ──────────────────────
    if session.state == SessionState.IMPLEMENTATION_PLANNED:
        from alarmv3.core.implementation import clone_source_to_target
        target = Path(args.target).resolve()
        if target.exists():
            log(f"Target {target} exists; using existing")
        else:
            log(f"Cloning source to {target}...")
            clone_source_to_target(session.source_path, target)
        session.set_metadata("target_path", str(target))
        session.transition_to(SessionState.WORKING_REPO_READY)

    # ── Phase 4 main: implement_batch with autopilot auto-accept ─────────
    if session.state == SessionState.WORKING_REPO_READY:
        ensure_autopilot(session.alarm_dir)
        log(f"Running implementation batch (max_concurrent={args.max_concurrent})...")
        log("  This takes ~1-2 min per item. Sit back.")
        from alarmv3.core.implementation import ImplementationRunner
        results = ImplementationRunner(session).run_batch(args.max_concurrent)

        auto = sum(1 for r in results if r.get("auto_accepted"))
        pending = sum(1 for r in results if not r.get("auto_accepted") and "error" not in r)
        errors = sum(1 for r in results if "error" in r)
        log(f"Implementation: {auto} auto-accepted, {pending} pending, {errors} errors")

        if pending:
            log("  Manually accepting remaining items...")
            from alarmv3.core.implementation import ImplementationRunner as IR
            runner = IR(session)
            for r in results:
                if not r.get("auto_accepted") and "error" not in r:
                    cid = r.get("change_id")
                    if cid is not None:
                        try:
                            runner.accept_change(cid, _auto_reason="non-interactive")
                        except Exception as e:
                            log(f"  accept_change({cid}) failed: {e}")

    log("=" * 60)
    log("RUN COMPLETE")
    log(f"Session    : {session.session_id}")
    log(f"State      : {session.state.value}")
    log(f"Artifacts  : {session.artifact_dir}")
    log(f"Target     : {session.get_metadata().get('target_path', '(none)')}")


if __name__ == "__main__":
    main()
