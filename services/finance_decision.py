"""Decision helpers for finance bot routing.

The AI/parser may propose values, but this layer decides whether the bot can
act automatically or must ask the group for clarification.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProjectResolutionDecision:
    action: str
    final_name: Optional[str] = None
    suggested_name: Optional[str] = None
    reason: str = ""

    @property
    def should_accept(self) -> bool:
        return self.action == "accept"

    @property
    def should_confirm(self) -> bool:
        return self.action == "confirm"


def _match_count(result: dict, default: int = 2) -> int:
    try:
        return int(result.get("match_count", default) or default)
    except (TypeError, ValueError):
        return default


def decide_project_resolution(
    result: dict,
    *,
    auto_accept_unique_ambiguous: bool = False,
) -> ProjectResolutionDecision:
    """Convert a project resolver result into a clear bot action."""
    status = (result or {}).get("status")
    final_name = (result or {}).get("final_name")
    original = (result or {}).get("original")

    if status in {"EXACT", "AUTO_FIX"} and final_name:
        return ProjectResolutionDecision(
            action="accept",
            final_name=final_name,
            reason=str(status).lower(),
        )

    if status == "AMBIGUOUS":
        unique = _match_count(result) == 1
        if auto_accept_unique_ambiguous and unique and final_name:
            return ProjectResolutionDecision(
                action="accept",
                final_name=final_name,
                reason="unique_ambiguous",
            )
        return ProjectResolutionDecision(
            action="confirm",
            suggested_name=final_name or original,
            reason="ambiguous",
        )

    if status == "NEW":
        return ProjectResolutionDecision(
            action="new",
            final_name=final_name or original,
            suggested_name=final_name or original,
            reason="new_project",
        )

    if status == "OPERATIONAL":
        return ProjectResolutionDecision(
            action="operational",
            reason="operational_keyword",
        )

    return ProjectResolutionDecision(
        action="confirm",
        suggested_name=final_name or original,
        reason="unknown_project_resolution",
    )
