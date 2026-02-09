from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from uk_address_matcher import run_matching, ExactMatchStage, UniqueTrigramStage

if TYPE_CHECKING:
    import duckdb

    from uk_address_matcher.sql_pipeline.runner import DebugOptions


def run_deterministic_pipeline(
    *,
    con: duckdb.DuckDBPyConnection,
    df_to_match: duckdb.DuckDBPyRelation,
    df_canonical: duckdb.DuckDBPyRelation,
    enabled_stage_names: Optional[list[str]] = None,
    pipeline_name: str,
    debug_options: Optional[DebugOptions] = None,
    explain: bool = False,
) -> duckdb.DuckDBPyRelation:
    """Run deterministic matching pipeline using run_matching."""
    from uk_address_matcher.linking_model.matching.stages import (
        PeeledAddressStage,
    )

    _name_to_stage = {
        "unique_trigram": UniqueTrigramStage(),
        "peeled_address": PeeledAddressStage(),
    }

    stages = [ExactMatchStage()]
    if enabled_stage_names:
        print(f"Running with additional enabled stages: {enabled_stage_names}")
        for name in enabled_stage_names:
            stage_key = name.value if hasattr(name, "value") else name
            if stage_key in _name_to_stage:
                stages.append(_name_to_stage[stage_key])

    relation = run_matching(
        con=con,
        df_messy_clean=df_to_match,
        df_canonical_clean=df_canonical,
        stages=stages,
        debug_options=debug_options,
        explain=explain,
    )
    show_relation(
        f"Final matches from deterministic pipeline: {pipeline_name}", relation
    )
    return relation


def show_relation(
    title: str,
    relation: duckdb.DuckDBPyRelation,
    *,
    limit: Optional[int] = None,
) -> None:
    """Display a DuckDB relation with optional row limit."""
    print(f"\n=== {title} ===")
    relation_to_show = relation.limit(limit) if limit is not None else relation
    relation_to_show.show(max_width=20000)
