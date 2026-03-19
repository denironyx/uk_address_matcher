from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb


def build_stage_breakdown(
    accuracy_relation: duckdb.DuckDBPyRelation,
) -> duckdb.DuckDBPyRelation:
    """Return stage-level rows from the accuracy table, excluding overall."""
    return accuracy_relation.filter("stage != 'overall'")
