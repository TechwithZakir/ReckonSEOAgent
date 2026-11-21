from typing import Any

from reckon_core.persistence import SeoActionProposal


class FixtureActionExecutor:
    """Local test-only executor; never performs network or CMS writes."""

    binding_version = "fixture-executor-v1"

    def execute(self, proposal: SeoActionProposal) -> dict[str, str]:
        if proposal.status not in {"approved", "executing"}:
            raise RuntimeError("Only approved proposals may execute.")
        return {
            **proposal.proposed_state,
            "target_version": proposal.target_version,
            "execution": "fixture-confirmed",
        }

    def verify(self, proposal: SeoActionProposal) -> dict[str, str]:
        if proposal.executed_state is None:
            raise RuntimeError("No executed state is available for verification.")
        for key, value in proposal.proposed_state.items():
            if proposal.executed_state.get(key) != value:
                raise RuntimeError("Executed state differs from approved proposal.")
        return {
            **proposal.executed_state,
            "verification": "fixture-confirmed",
        }

    def rollback(self, proposal: SeoActionProposal) -> dict[str, str]:
        return {
            **proposal.before_state,
            "rollback": "fixture-confirmed",
        }
