"""Conditional auto-acceptance policy for low-risk implementation changes.

Phase 5. Reads .alarmv3/policy/autopilot.yaml (GOVERNANCE zone — human-written only).
When the evaluator's risk_level falls within a rule's threshold, the change is
auto-committed without a human review gate. Every auto-acceptance is audit-logged.

If the policy file does not exist, auto-accept is fully disabled (safe default).
"""

from pathlib import Path
from typing import Optional

import yaml

_EFFORT_ORDER = {"S": 1, "M": 2, "L": 3, "XL": 4}

_POLICY_TEMPLATE = """\
# ALARMv3 Autopilot Policy
# GOVERNANCE zone — only humans should edit this file.
#
# When enabled: changes whose evaluator risk_level <= max_risk_level AND
# whose effort <= max_effort are auto-accepted and committed without a human gate.
# All auto-acceptances are written to the session audit log.

enabled: false   # set to true to activate

rules: []

# Example rules (uncomment and adjust as needed):
#
#   # Auto-accept trivial documentation improvements
#   - category: quality
#     max_risk_level: 1     # evaluator 1-5 scale (1 = trivial, 5 = high-risk)
#     max_effort: S         # S | M | L | XL
#     description: "Docstring / comment-only quality fixes"
#
#   # Auto-accept minor dependency version pins (no logic changes expected)
#   - category: dependency
#     max_risk_level: 2
#     max_effort: S
#     description: "Patch-level dependency updates"
"""


class AutopilotPolicy:
    """Reads the autopilot policy from the GOVERNANCE zone and evaluates change eligibility."""

    def __init__(self, alarm_dir: Path):
        self._policy_path = alarm_dir / "policy" / "autopilot.yaml"

    # ── Policy access ──────────────────────────────────────────────────────

    def get_policy(self) -> dict:
        """Return the parsed policy, or a safe disabled default if absent or invalid."""
        if not self._policy_path.exists():
            return {
                "enabled": False,
                "rules": [],
                "note": "No policy file found at .alarmv3/policy/autopilot.yaml — "
                        "auto-accept is disabled. Call init_autopilot_policy to create one.",
            }
        try:
            with open(self._policy_path) as f:
                loaded = yaml.safe_load(f)
            if not isinstance(loaded, dict):
                return {"enabled": False, "rules": [], "error": "Policy file is not a YAML mapping"}
            return loaded
        except Exception as exc:
            return {"enabled": False, "rules": [], "error": str(exc)}

    def should_auto_accept(
        self,
        category: str,
        risk_level: Optional[int],
        effort: Optional[str],
    ) -> tuple[bool, str]:
        """Return (True, matching_rule_description) if auto-accept applies, else (False, reason)."""
        policy = self.get_policy()
        if not policy.get("enabled"):
            return False, "autopilot disabled"
        if risk_level is None:
            return False, "no risk_level from evaluator"
        for rule in policy.get("rules", []):
            if rule.get("category") != category:
                continue
            max_risk = int(rule.get("max_risk_level", 0))
            max_effort = rule.get("max_effort", "S")
            if risk_level > max_risk:
                continue
            if effort and _EFFORT_ORDER.get(effort, 99) > _EFFORT_ORDER.get(max_effort, 1):
                continue
            desc = rule.get("description", f"category={category} rule")
            return True, desc
        return False, f"no matching rule for category={category!r} risk={risk_level}"

    def init_template(self) -> str:
        """Write the template policy file if none exists. Returns its path as a string."""
        self._policy_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._policy_path.exists():
            self._policy_path.write_text(_POLICY_TEMPLATE)
        return str(self._policy_path)
