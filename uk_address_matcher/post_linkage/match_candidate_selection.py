from __future__ import annotations

from typing import Optional

import duckdb

from uk_address_matcher.sql_pipeline.match_reasons import MatchReason
from uk_address_matcher.sql_pipeline.runner import (
    DebugOptions,
    InputBinding,
    create_sql_pipeline,
)
from uk_address_matcher.sql_pipeline.steps import CTEStep, pipeline_stage


@pipeline_stage(
    name="prepare_match_candidates",
    description="Attach canonical address details to match candidates.",
    tags=["post_linkage", "matching"],
    stage_output="match_candidates",
)
def _prepare_match_candidates(
    *, source_cte: str, include_ukam_label: bool = False
) -> list[CTEStep]:
    """Join selected matches with canonical address details."""

    canonical_sql = """
        SELECT
            ukam_address_id,
            original_address_concat AS original_address_concat_canonical,
            postcode AS postcode_canonical
        FROM {canonical_addresses__ukam}
    """

    ukam_label_final = "selected.ukam_label," if include_ukam_label else ""
    final_sql = f"""
        SELECT
            selected.unique_id,
            {ukam_label_final}
            selected.resolved_canonical_id,
            selected.original_address_concat,
            canon.original_address_concat_canonical,
            selected.postcode,
            canon.postcode_canonical,
            selected.match_weight,
            selected.distinguishability,
            selected.distinguishability_category,
            selected.match_reason,
            selected.ukam_address_id,
            selected.canonical_ukam_address_id
        FROM {{{source_cte}}} AS selected
        LEFT JOIN {{canonical_projection__ukam}} AS canon
            ON canon.ukam_address_id = selected.canonical_ukam_address_id
        ORDER BY selected.unique_id
    """

    return [
        CTEStep("canonical_projection__ukam", canonical_sql),
        CTEStep("match_candidates__ukam", final_sql),
    ]


@pipeline_stage(
    name="prepare_splink_candidates",
    description="Filter Splink matches to the top-ranked candidate per fuzzy address.",
    tags=["post_linkage", "splink"],
    stage_output="splink_top__ukam",
)
def _prepare_splink_candidates(
    *,
    match_weight_threshold: float,
    distinguishability_threshold: Optional[float],
    include_ukam_label: bool = False,
) -> list[CTEStep]:
    """Filter Splink matches and retain the best candidate for each fuzzy ID."""

    enum_values = MatchReason.enum_values()
    enum_literal = ", ".join(f"'{value}'" for value in enum_values)
    splink_label = MatchReason.SPLINK.value.replace("'", "''")

    distinguishability_filter = ""
    if distinguishability_threshold is not None:
        # If distinguishability is null, then there was only one plausible candidate
        # so these rows should be retained
        distinguishability_filter = (
            "AND (distinguishability IS NULL "
            f"OR distinguishability >= {distinguishability_threshold})"
        )

    ukam_label_select = "ukam_label_r AS ukam_label," if include_ukam_label else ""

    # _r = record from addresses to match (fuzzy)
    # _l = record from addresses to search within (canonical)
    top_sql = f"""
        SELECT
            unique_id_r AS unique_id,
            {ukam_label_select}
            unique_id_l AS resolved_canonical_id,
            ukam_address_id_r as ukam_address_id,
            ukam_address_id_l as canonical_ukam_address_id,
            address_concat_r as original_address_concat,
            postcode_r as postcode,
            '{splink_label}'::ENUM({enum_literal}) AS match_reason,
            match_weight,
            distinguishability,
            distinguishability_category
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY unique_id_r
                    ORDER BY match_weight DESC, distinguishability DESC NULLS LAST, unique_id_l
                ) AS match_rank
            FROM {{splink_matches__ukam}}
            WHERE match_weight >= {match_weight_threshold}
            {distinguishability_filter}
        ) AS ranked
        WHERE match_rank = 1
    """

    return [CTEStep("splink_top__ukam", top_sql)]


@pipeline_stage(
    name="combine_exact_and_splink_matches",
    description="Merge deterministic and Splink matches into a single relation.",
    tags=["post_linkage", "matching"],
    stage_output="combined_matches",
)
def _combine_exact_and_splink_matches(
    *, include_ukam_label: bool = False
) -> list[CTEStep]:
    """Union exact and Splink matches into a single relation."""

    ukam_label_field = "ukam_label," if include_ukam_label else ""
    common_fields = f"""
        unique_id,
        {ukam_label_field}
        resolved_canonical_id,
        ukam_address_id,
        canonical_ukam_address_id,
        original_address_concat,
        postcode,
        match_reason,
        match_weight,
        distinguishability,
        distinguishability_category
    """

    union_sql = f"""
        SELECT
            {common_fields}
        FROM {{exact_top__ukam}}

        UNION ALL

        SELECT
            {common_fields}
        FROM {{splink_top__ukam}}
        -- Ensures we don't duplicate exact matches if they also appear in Splink
        WHERE ukam_address_id NOT IN (
            SELECT ukam_address_id FROM {{exact_top__ukam}} WHERE match_reason IS NOT NULL
        )
    """

    return [
        CTEStep("combined_matches__ukam", union_sql),
    ]


@pipeline_stage(
    name="prepare_exact_candidates",
    description="Filter deterministic matches and shape columns for matching output.",
    tags=["post_linkage", "matching"],
    stage_output="exact_top__ukam",
)
def _prepare_exact_candidates(
    *,
    include_unmatched: bool,
    exclude_splink_matches: bool,
    include_ukam_label: bool = False,
) -> list[CTEStep]:
    """Filter exact matches and align fields with Splink outputs."""

    ukam_label_field = "ukam_label," if include_ukam_label else ""

    if include_unmatched:
        if exclude_splink_matches:
            exact_filter = """
                WHERE match_reason IS NOT NULL
                OR (match_reason IS NULL AND ukam_address_id NOT IN
                    (SELECT ukam_address_id FROM {splink_top__ukam}))
            """
        else:
            exact_filter = ""
    else:
        exact_filter = "WHERE match_reason IS NOT NULL"

    exact_sql = f"""
        SELECT
            unique_id,
            {ukam_label_field}
            resolved_canonical_id,
            ukam_address_id,
            canonical_ukam_address_id,
            original_address_concat,
            postcode,
            match_reason,
            NULL AS match_weight,
            NULL AS distinguishability,
            NULL AS distinguishability_category
        FROM {{exact_matches__ukam}}
        {exact_filter}
    """

    return [CTEStep("exact_top__ukam", exact_sql)]


def select_top_match_candidates(
    *,
    con: duckdb.DuckDBPyConnection,
    df_exact_matches: Optional[duckdb.DuckDBPyRelation] = None,
    df_splink_matches: Optional[duckdb.DuckDBPyRelation] = None,
    df_canonical: duckdb.DuckDBPyRelation,
    match_weight_threshold: float = 10.0,
    distinguishability_threshold: Optional[float] = 5.0,
    include_unmatched: bool = False,
    debug_options: Optional[DebugOptions] = None,
) -> duckdb.DuckDBPyRelation:
    """Combine deterministic and Splink matches using the SQL pipeline framework.

    Args:
        con: DuckDB connection
        df_exact_matches: Exact match results (optional)
        df_splink_matches: Splink match candidates (optional)
        df_canonical: Canonical addresses
        match_weight_threshold: Minimum match weight for Splink matches
        distinguishability_threshold: Minimum distinguishability for Splink matches
        include_unmatched: If True, include unmatched records from exact_matches
        debug_options: Debug options for pipeline execution

    Raises:
        ValueError: When both df_exact_matches and df_splink_matches are omitted.
    """

    if df_exact_matches is None and df_splink_matches is None:
        raise ValueError(
            "Provide at least one of df_exact_matches or df_splink_matches."
        )

    include_ukam_label = False
    if df_splink_matches is not None and "ukam_label_r" in df_splink_matches.columns:
        include_ukam_label = True
    if df_exact_matches is not None and "ukam_label" in df_exact_matches.columns:
        include_ukam_label = True

    if (
        df_exact_matches is not None
        and include_ukam_label
        and "ukam_label" not in df_exact_matches.columns
    ):
        df_exact_matches = df_exact_matches.select("*, NULL::VARCHAR AS ukam_label")

    if (
        df_splink_matches is not None
        and include_ukam_label
        and "ukam_label_r" not in df_splink_matches.columns
    ):
        df_splink_matches = df_splink_matches.select("*, NULL::VARCHAR AS ukam_label_r")

    input_rel = [InputBinding("canonical_addresses__ukam", df_canonical)]
    stage_specs = []

    if df_splink_matches is not None:
        input_rel.append(InputBinding("splink_matches__ukam", df_splink_matches))
        stage_specs.append(
            _prepare_splink_candidates(
                match_weight_threshold=match_weight_threshold,
                distinguishability_threshold=distinguishability_threshold,
                include_ukam_label=include_ukam_label,
            )
        )

    if df_exact_matches is not None:
        input_rel.append(InputBinding("exact_matches__ukam", df_exact_matches))
        stage_specs.append(
            _prepare_exact_candidates(
                include_unmatched=include_unmatched,
                exclude_splink_matches=df_splink_matches is not None,
                include_ukam_label=include_ukam_label,
            )
        )

    if df_exact_matches is not None and df_splink_matches is not None:
        stage_specs.append(
            _combine_exact_and_splink_matches(include_ukam_label=include_ukam_label)
        )
        stage_specs.append(
            _prepare_match_candidates(
                source_cte="combined_matches__ukam",
                include_ukam_label=include_ukam_label,
            )
        )
    elif df_exact_matches is not None:
        stage_specs.append(
            _prepare_match_candidates(
                source_cte="exact_top__ukam",
                include_ukam_label=include_ukam_label,
            )
        )
    else:
        stage_specs.append(
            _prepare_match_candidates(
                source_cte="splink_top__ukam",
                include_ukam_label=include_ukam_label,
            )
        )

    pipeline = create_sql_pipeline(
        con,
        input_rel,
        stage_specs,
        pipeline_name="Match candidate selection",
        pipeline_description="Filter matches and merge with deterministic outputs.",
    )

    if debug_options is not None and debug_options.debug_mode:
        pipeline.show_plan()

    return pipeline.run(options=debug_options)


__all__ = ["select_top_match_candidates"]
