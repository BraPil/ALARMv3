"""Guardrail state machine, trust zone enforcement, and WORM audit log.

The state machine is the primary safety layer. All MCP tools must call
require_state() before executing. Violations raise GuardrailViolation
which the MCP layer propagates as a tool error — the LLM cannot bypass this.
"""

import json
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Optional


class SessionState(str, Enum):
    UNATTACHED = "UNATTACHED"
    ATTACHED = "ATTACHED"
    READ_ONLY_CONFIRMED = "READ_ONLY_CONFIRMED"
    ANALYSIS_IN_PROGRESS = "ANALYSIS_IN_PROGRESS"
    RECOMMENDATIONS_PENDING_REVIEW = "RECOMMENDATIONS_PENDING_REVIEW"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    IMPLEMENTATION_PLANNED = "IMPLEMENTATION_PLANNED"
    WORKING_REPO_READY = "WORKING_REPO_READY"


# The only permitted state transitions — enforced at the MCP layer.
_TRANSITIONS: dict[SessionState, list[SessionState]] = {
    SessionState.UNATTACHED:                       [SessionState.ATTACHED],
    SessionState.ATTACHED:                         [SessionState.READ_ONLY_CONFIRMED],
    SessionState.READ_ONLY_CONFIRMED:              [SessionState.ANALYSIS_IN_PROGRESS],
    SessionState.ANALYSIS_IN_PROGRESS:             [SessionState.RECOMMENDATIONS_PENDING_REVIEW],
    SessionState.RECOMMENDATIONS_PENDING_REVIEW:   [SessionState.ANALYSIS_COMPLETE],
    SessionState.ANALYSIS_COMPLETE:                [SessionState.IMPLEMENTATION_PLANNED],
    SessionState.IMPLEMENTATION_PLANNED:           [SessionState.WORKING_REPO_READY],
    SessionState.WORKING_REPO_READY:               [],
}


# States where knowledge querying is permitted
ANALYSIS_COMPLETE_STATES = [
    SessionState.RECOMMENDATIONS_PENDING_REVIEW,
    SessionState.ANALYSIS_COMPLETE,
    SessionState.IMPLEMENTATION_PLANNED,
    SessionState.WORKING_REPO_READY,
]


class GuardrailViolation(Exception):
    """Raised when a guardrail constraint is violated.

    This exception is intentionally not caught inside the core engine —
    it propagates to the MCP or CLI layer, which surfaces it to the user.
    """


class GuardrailsManager:
    """Enforces state transitions, trust zone isolation, and WORM audit log."""

    def __init__(self, artifact_dir: Path):
        self._artifact_dir = artifact_dir
        self._audit_log = artifact_dir / "audit.log"
        self._lock = threading.Lock()

    # ── State enforcement ──────────────────────────────────────────────────

    def require_state(self, current: SessionState, required: SessionState) -> None:
        if current != required:
            raise GuardrailViolation(
                f"Operation requires state {required.value}, "
                f"current state is {current.value}."
            )

    def require_state_in(self, current: SessionState, required: list[SessionState]) -> None:
        if current not in required:
            names = [s.value for s in required]
            raise GuardrailViolation(
                f"Operation requires one of {names}, "
                f"current state is {current.value}."
            )

    def transition(self, current: SessionState, target: SessionState) -> SessionState:
        allowed = _TRANSITIONS.get(current, [])
        if target not in allowed:
            raise GuardrailViolation(
                f"Transition {current.value} → {target.value} is not permitted. "
                f"Allowed from {current.value}: {[s.value for s in allowed]}"
            )
        self._audit(f"STATE_TRANSITION {current.value} -> {target.value}")
        return target

    # ── Trust zone enforcement ─────────────────────────────────────────────

    def assert_no_write_to_source(self, path: Path, source_root: Path) -> None:
        """Raises GuardrailViolation if path is inside the source zone."""
        try:
            path.resolve().relative_to(source_root.resolve())
            raise GuardrailViolation(
                f"Write to source zone is forbidden: {path}\n"
                f"The source repository is a read-only archive."
            )
        except ValueError:
            pass  # path is outside source_root — safe

    def assert_no_execute(self, path: Path, source_root: Path) -> None:
        """Raises GuardrailViolation if path would execute analyzed source code."""
        try:
            path.resolve().relative_to(source_root.resolve())
            raise GuardrailViolation(
                f"Execution of analyzed source code is forbidden: {path}\n"
                f"Analyzed code is never executed."
            )
        except ValueError:
            pass  # path is outside source_root — safe

    def assert_target_gated(self, current: SessionState) -> None:
        """Raises if attempting to write to the target zone before approval."""
        self.require_state_in(
            current,
            [SessionState.IMPLEMENTATION_PLANNED, SessionState.WORKING_REPO_READY],
        )

    # ── Audit log ──────────────────────────────────────────────────────────

    def log_tool_call(self, tool: str, args: dict) -> None:
        self._audit(f"TOOL_CALL {tool}", {"args": args})

    def log_error(self, tool: str, error: str) -> None:
        self._audit(f"TOOL_ERROR {tool}", {"error": error})

    def _audit(self, message: str, extra: Optional[dict] = None) -> None:
        """Append-only WORM audit log. Never truncate this file."""
        entry: dict = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "msg": message,
        }
        if extra:
            entry.update(extra)
        line = json.dumps(entry) + "\n"
        with self._lock:
            self._audit_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self._audit_log, "a") as f:
                f.write(line)
