"""ThreadPoolExecutor harness and SQLite work queue orchestration.

The orchestrator coordinates the three analysis phases (discovery → analysis →
synthesis) as sequential phase gates with parallel workers within each phase.
Each phase produces a durable SQLite artifact before the next begins — if the
session is interrupted, progress is not lost.

Board decision: MAX_WORKERS=4 (Codespaces-safe). Configurable via session config.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .session import Session


class Orchestrator:
    """Manages the three-phase analysis pipeline for a session."""

    MAX_WORKERS = 4  # safe for GitHub Codespaces; raise for developer machines

    def __init__(self, session: Session, max_workers: Optional[int] = None):
        self._session = session
        self._max_workers = max_workers or self.MAX_WORKERS
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ── Public API (called by MCP tools and CLI) ───────────────────────────

    def start_mapping(self) -> str:
        """Start file discovery in a background thread. Returns job_id."""
        source = self._session.source_path
        if not source:
            raise ValueError("No source path attached to session")

        job_id = self._new_job("mapping")
        thread = threading.Thread(
            target=self._run_mapping,
            args=(job_id, source),
            daemon=True,
            name=f"alarmv3-mapping-{job_id[:8]}",
        )
        thread.start()
        return job_id

    def start_analysis(self) -> str:
        """Start dependency/symbol analysis in a background thread. Returns job_id."""
        job_id = self._new_job("analysis")
        thread = threading.Thread(
            target=self._run_analysis,
            args=(job_id,),
            daemon=True,
            name=f"alarmv3-analysis-{job_id[:8]}",
        )
        thread.start()
        return job_id

    def synthesize_recommendations(self, aaa_grounding: "str | None" = None) -> dict:
        """Run synthesis then adversarial evaluation. Returns combined result dict."""
        from .evaluation import RecommendationEvaluator
        from .synthesis import Synthesizer

        synthesizer = Synthesizer(self._session)
        synth_result = synthesizer.run(aaa_grounding=aaa_grounding)

        evaluator = RecommendationEvaluator(self._session)
        evaluations = evaluator.evaluate(
            synth_result["recommendations"],
            synthesizer._build_context(),
        )
        evaluator.store_evaluations(evaluations)

        verdict_summary = _tally_verdicts(evaluations)
        return {
            **synth_result,
            "evaluator_summary": verdict_summary,
            "message": (
                f"Generated {synth_result['recommendation_count']} recommendations. "
                f"Evaluator: {verdict_summary['accept']} accept, "
                f"{verdict_summary['revise']} revise, "
                f"{verdict_summary['reject']} reject. "
                "Review at recommendations://evaluated then call review_recommendations."
            ),
        }

    def get_job_status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
        if job:
            return {"job_id": job_id, **job}
        # Fall back to queue stats for the phase
        return {"job_id": job_id, "status": "unknown"}

    # ── Phase runners (background threads) ────────────────────────────────

    def _run_mapping(self, job_id: str, source) -> None:
        try:
            from .discovery import FileScanner
            scanner = FileScanner(source, self._session)
            with ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="alarmv3-scan",
            ) as pool:
                total = scanner.scan(pool, job_id)
            self._finish_job(job_id, files_discovered=total)
        except Exception as e:
            self._fail_job(job_id, str(e))

    def _run_analysis(self, job_id: str) -> None:
        try:
            from .analysis import Analyzer
            analyzer = Analyzer(self._session)
            with ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="alarmv3-parse",
            ) as pool:
                stats = analyzer.run(pool, job_id)
            self._finish_job(job_id, **stats)
        except Exception as e:
            self._fail_job(job_id, str(e))

    # ── Job registry helpers ───────────────────────────────────────────────

    def _new_job(self, phase: str) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = {"status": "running", "phase": phase, "progress": 0}
        return job_id

    def _finish_job(self, job_id: str, **extra) -> None:
        with self._lock:
            self._jobs[job_id] = {"status": "complete", "progress": 100, **extra}

    def _fail_job(self, job_id: str, error: str) -> None:
        with self._lock:
            self._jobs[job_id] = {"status": "failed", "error": error}


def _tally_verdicts(evaluations: list[dict]) -> dict:
    tally: dict[str, int] = {"accept": 0, "revise": 0, "reject": 0, "pending": 0}
    for ev in evaluations:
        verdict = ev.get("verdict", "pending")
        tally[verdict] = tally.get(verdict, 0) + 1
    return tally
