from __future__ import annotations

from typing import Literal

from uk_address_matcher.sql_pipeline.match_reasons import MatchReason
from uk_address_matcher.sql_pipeline.steps import CTEStep, pipeline_stage

MessyInputName = Literal["messy_addresses", "unmatched_records"]


@pipeline_stage(
    name="annotate_exact_matches",
    description=(
        "Annotate messy addresses with exact hash-join matches on "
        "clean_full_address + postcode"
    ),
    tags=["phase_1", "exact_matching"],
    depends_on=["restrict_canonical_to_messy_postcodes"],
)
def _annotate_exact_matches(
    messy_input_name: MessyInputName = "messy_addresses",
) -> list[CTEStep]:
    """Annotate messy addresses with exact matches.

    Parameters
    ----------
    messy_input_name:
        The placeholder name for the messy input table. Defaults to "messy_addresses" for
        the initial pass. Can be set to "unmatched_records" when running after filtering.
    """
    match_condition = """
        messy.clean_full_address = canon.clean_full_address
        AND messy.postcode = canon.postcode
    """

    # TODO(ThomasHepworth): For now, we are deduplicating on exact matches, where a
    # a single address appears multiple times in the canonical dataset. This should be
    # reviewed later to see if we can improve handling of these cases.
    exact_value = MatchReason.EXACT.value
    enum_values = str(MatchReason.enum_values())
    annotated_sql = f"""
        SELECT
            messy.ukam_address_id AS ukam_address_id,
            matched_canon.ukam_address_id AS canonical_ukam_address_id,
            matched_canon.canonical_unique_id AS resolved_canonical_id,
            '{exact_value}'::ENUM {enum_values} as match_reason
        FROM {{{messy_input_name}}} AS messy
        INNER JOIN LATERAL (
            SELECT
                canon.ukam_address_id as ukam_address_id,
                canon.canonical_unique_id as canonical_unique_id
            FROM {{canonical_addresses_restricted}} AS canon
            WHERE {match_condition}
            -- If we get multiple matches, we just take the first one
            -- Usually an indication that the canonical dataset has duplicates
            LIMIT 1
        ) AS matched_canon ON true
    """

    return [
        CTEStep("annotated_exact_matches", annotated_sql),
    ]


__all__ = ["_annotate_exact_matches"]
