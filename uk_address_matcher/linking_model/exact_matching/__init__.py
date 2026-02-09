from __future__ import annotations

from uk_address_matcher.linking_model.matching.runner import run_matching

# Re-export run_matching as run_deterministic_match_pass for any remaining callers
run_deterministic_match_pass = run_matching

__all__ = [
    "run_deterministic_match_pass",
]
