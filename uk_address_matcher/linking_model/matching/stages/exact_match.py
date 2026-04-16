from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

from uk_address_matcher.linking_model.matching.input_filters import (
    _restrict_canonical_to_messy_postcodes,
)
from uk_address_matcher.linking_model.matching.stages.base_stage import MatchingStage
from uk_address_matcher.sql_pipeline.match_reasons import MatchReason
from uk_address_matcher.sql_pipeline.steps import CTEStep, pipeline_stage

if TYPE_CHECKING:
    import duckdb

    from uk_address_matcher.sql_pipeline.runner import DebugOptions

MessyInputName = Literal["__ukam__tmp_messy_addresses", "unmatched_records"]


@dataclass(frozen=True, repr=False)
class ExactMatchStage(MatchingStage):
    """Deterministic exact matching on ``clean_full_address`` and ``postcode``.

    This is usually the first stage in a pipeline. It accepts the easy,
    unambiguous cases before any probabilistic matching is attempted.

    A match is emitted when the cleaned messy address and the cleaned canonical
    address are identical and the postcode is also identical. A cleaned address
    match on its own is not enough: differing postcodes will not match.

    Example:
        ``"10 Demo Road Townton"`` matches
        ``"10 Demo Road, Townton"`` only when cleaning normalises punctuation
        and whitespace and both records have the same postcode.
    """

    def find_matches(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_name: str,
        df_unmatched: duckdb.DuckDBPyRelation,
        df_canonical: duckdb.DuckDBPyRelation,
        debug_options: Optional[DebugOptions] = None,
        explain: bool = False,
    ) -> Optional[duckdb.DuckDBPyRelation]:
        from uk_address_matcher.linking_model.matching.stages._sql_helpers import (
            run_sql_pipeline,
        )

        return run_sql_pipeline(
            con=con,
            pipeline_stages=[
                _restrict_canonical_to_messy_postcodes("exact"),
                _exact_matches("__ukam__tmp_messy_addresses"),
            ],
            stage_name=stage_name,
            df_unmatched=df_unmatched,
            df_canonical=df_canonical,
            debug_options=debug_options,
            explain=explain,
        )


@pipeline_stage(
    name="exact_matches",
    description="Match using exact hash-join on clean_full_address + postcode",
    tags=["phase_1", "matching"],
    depends_on=["restrict_canonical_to_messy_postcodes"],
)
def _exact_matches(
    messy_input_name: MessyInputName = "__ukam__tmp_messy_addresses",
) -> list[CTEStep]:
    """Find exact and no-whitespace postcode-bounded matches.

    Uses set-based equality joins and then selects one deterministic best
    candidate per messy record, preferring exact matches over no-whitespace
    matches.

    Parameters
    ----------
    messy_input_name:
        The placeholder name for the messy input table. Defaults to
        "__ukam__tmp_messy_addresses" for the initial pass. Can be set
        to "unmatched_records" when running after filtering.
    """
    exact_match_condition = """
        messy.clean_full_address = canon.clean_full_address
        AND messy.postcode = canon.postcode
    """

    exact_value = MatchReason.EXACT.value
    exact_no_whitespace_value = MatchReason.EXACT_NO_WHITESPACE.value
    enum_values = str(MatchReason.enum_values())
    no_ws_expression = "regexp_replace(clean_full_address, '\\s+', '', 'g')"

    messy_match_keys_sql = f"""
        SELECT
            messy.ukam_address_id,
            messy.postcode,
            messy.clean_full_address,
            {no_ws_expression} AS clean_full_address_no_ws
        FROM {{{messy_input_name}}} AS messy
    """

    canonical_match_keys_sql = f"""
        SELECT
            canon.ukam_address_id AS canonical_ukam_address_id,
            canon.canonical_unique_id,
            canon.postcode,
            canon.clean_full_address,
            {no_ws_expression} AS clean_full_address_no_ws
        FROM {{canonical_addresses_restricted}} AS canon
    """

    exact_candidates_sql = f"""
        SELECT
            messy.ukam_address_id AS ukam_address_id,
            canon.canonical_ukam_address_id,
            canon.canonical_unique_id AS resolved_canonical_id,
            '{exact_value}'::ENUM {enum_values} AS match_reason,
            1 AS match_priority
        FROM {{messy_match_keys}} AS messy
        INNER JOIN {{canonical_match_keys}} AS canon
            ON {exact_match_condition}
    """

    no_ws_candidates_sql = f"""
        SELECT
            messy.ukam_address_id AS ukam_address_id,
            canon.canonical_ukam_address_id,
            canon.canonical_unique_id AS resolved_canonical_id,
            '{exact_no_whitespace_value}'::ENUM {enum_values} AS match_reason,
            2 AS match_priority
        FROM {{messy_match_keys}} AS messy
        INNER JOIN {{canonical_match_keys}} AS canon
            ON messy.postcode = canon.postcode
            AND messy.clean_full_address_no_ws = canon.clean_full_address_no_ws
            AND messy.clean_full_address_no_ws <> ''
            AND messy.clean_full_address <> canon.clean_full_address
    """

    all_exact_candidates_sql = """
        SELECT * FROM {exact_candidates}
        UNION ALL
        SELECT * FROM {no_ws_candidates}
    """

    ranked_exact_candidates_sql = """
        SELECT
            candidates.ukam_address_id,
            candidates.canonical_ukam_address_id,
            candidates.resolved_canonical_id,
            candidates.match_reason,
            ROW_NUMBER() OVER (
                PARTITION BY candidates.ukam_address_id
                ORDER BY
                    candidates.match_priority,
                    candidates.canonical_ukam_address_id
            ) AS rn
        FROM {all_exact_candidates} AS candidates
    """

    exact_matches_sql = """
        SELECT
            ukam_address_id,
            canonical_ukam_address_id,
            resolved_canonical_id,
            match_reason
        FROM {ranked_exact_candidates}
        WHERE rn = 1
    """

    return [
        CTEStep("messy_match_keys", messy_match_keys_sql),
        CTEStep("canonical_match_keys", canonical_match_keys_sql),
        CTEStep("exact_candidates", exact_candidates_sql),
        CTEStep("no_ws_candidates", no_ws_candidates_sql),
        CTEStep("all_exact_candidates", all_exact_candidates_sql),
        CTEStep("ranked_exact_candidates", ranked_exact_candidates_sql),
        CTEStep("exact_matches", exact_matches_sql),
    ]
