from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import TYPE_CHECKING, Optional

from uk_address_matcher.linking_model.matching.input_filters import (
    _restrict_canonical_to_messy_postcodes,
)
from uk_address_matcher.linking_model.matching.stages.base_stage import MatchingStage
from uk_address_matcher.sql_pipeline.match_reasons import MatchReason
from uk_address_matcher.sql_pipeline.steps import CTEStep, pipeline_stage

if TYPE_CHECKING:
    import duckdb

    from uk_address_matcher.sql_pipeline.runner import DebugOptions


@dataclass(frozen=True, repr=False)
class PeeledAddressStage(MatchingStage):
    """Deterministic matching after peeling common UK locality suffixes.

    This stage removes trailing locality words such as borough, county, or city
    names, then performs an exact match on the peeled address plus postcode.
    It is useful when one side includes extra suffixes such as ``"Hackney
    London"`` and the other does not, but it still requires the postcodes to
    be identical.

    Use this before ``SplinkStage`` so these high-precision cases are resolved
    without needing probabilistic thresholds.

    Example:
        ``"100 Test Street Hackney London"`` can match
        ``"100 Test Street"`` when both share the same postcode. Peeling only
        relaxes the address text comparison; it does not allow cross-postcode
        matches.
    """

    enable_whitespace_punctuation_stripping: bool = False

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
                _peeled_address_matches(
                    enable_whitespace_punctuation_stripping=(
                        self.enable_whitespace_punctuation_stripping
                    )
                ),
            ],
            stage_name=stage_name,
            df_unmatched=df_unmatched,
            df_canonical=df_canonical,
            debug_options=debug_options,
            explain=explain,
        )


@pipeline_stage(
    name="peeled_address_matching",
    description=(
        "Find matches by comparing addresses after peeling common UK end tokens "
        "(cities, counties, boroughs), with an optional whitespace/punctuation "
        "stripping fallback on the peeled shell."
    ),
    tags=["phase_1", "matching"],
    depends_on=["restrict_canonical_to_messy_postcodes"],
)
def _peeled_address_matches(
    *,
    enable_whitespace_punctuation_stripping: bool = False,
) -> list[CTEStep]:
    """Find matches using peeled addresses and an optional compacted fallback."""
    match_reason_value = MatchReason.PEELED_ADDRESS.value
    stripped_match_reason_value = MatchReason.PEELED_ADDRESS_STRIPPED.value
    enum_values = str(MatchReason.enum_values())

    messy_peeled_sql = _build_regex_peel_sql(
        source_placeholder="__ukam__tmp_messy_addresses",
        id_column="ukam_address_id",
        canonical=False,
    )

    canonical_peeled_sql = _build_regex_peel_sql(
        source_placeholder="canonical_addresses_restricted",
        id_column="ukam_address_id",
        canonical=True,
    )

    peeled_candidates_sql = f"""
        SELECT
            messy.ukam_address_id AS ukam_address_id,
            canon.canonical_ukam_address_id,
            canon.canonical_unique_id AS resolved_canonical_id,
            '{match_reason_value}'::ENUM {enum_values} AS match_reason,
            1 AS match_priority
        FROM {{messy_peeled}} AS messy
        INNER JOIN {{canonical_peeled}} AS canon
            ON messy.postcode = canon.postcode
            AND messy.peeled_address = canon.peeled_address
        WHERE messy.did_peel OR canon.did_peel
    """

    ranked_peeled_candidates_sql = """
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
        FROM {peeled_address_candidates} AS candidates
    """

    pre_stripped_matches_sql = """
        SELECT
            ukam_address_id,
            canonical_ukam_address_id,
            resolved_canonical_id,
            match_reason
        FROM {ranked_peeled_candidates}
        WHERE rn = 1
    """

    steps = [
        CTEStep("messy_peeled", messy_peeled_sql),
        CTEStep("canonical_peeled", canonical_peeled_sql),
        CTEStep("peeled_address_candidates", peeled_candidates_sql),
        CTEStep("ranked_peeled_candidates", ranked_peeled_candidates_sql),
        CTEStep("pre_stripped_matches", pre_stripped_matches_sql),
    ]

    if enable_whitespace_punctuation_stripping:
        messy_residual_sql = """
            SELECT messy.*
            FROM {messy_peeled} AS messy
            LEFT JOIN {pre_stripped_matches} AS matched
                ON matched.ukam_address_id = messy.ukam_address_id
            WHERE matched.ukam_address_id IS NULL
        """

        residual_postcodes_sql = """
            SELECT DISTINCT postcode
            FROM {messy_residual}
        """

        canonical_residual_sql = """
            SELECT canon.*
            FROM {canonical_peeled} AS canon
            SEMI JOIN {residual_postcodes} AS rp
                ON rp.postcode = canon.postcode
        """

        stripped_messy_sql = f"""
            SELECT
                messy.ukam_address_id,
                messy.postcode,
                messy.peeled_address,
                messy.did_peel,
                {_compacted_address_sql("messy.peeled_address")}
                    AS compact_peeled_address
            FROM {{messy_residual}} AS messy
        """

        stripped_canonical_sql = f"""
            SELECT
                canon.canonical_ukam_address_id,
                canon.canonical_unique_id,
                canon.postcode,
                canon.peeled_address,
                canon.did_peel,
                {_compacted_address_sql("canon.peeled_address")}
                    AS compact_peeled_address
            FROM {{canonical_residual}} AS canon
        """

        stripped_candidates_sql = f"""
            SELECT
                messy.ukam_address_id,
                canon.canonical_ukam_address_id,
                canon.canonical_unique_id AS resolved_canonical_id,
                '{stripped_match_reason_value}'::ENUM {enum_values} AS match_reason
            FROM {{stripped_messy}} AS messy
            INNER JOIN {{stripped_canonical}} AS canon
                ON messy.postcode = canon.postcode
                AND messy.compact_peeled_address = canon.compact_peeled_address
            WHERE messy.compact_peeled_address <> ''
            AND (messy.did_peel OR canon.did_peel)
            AND (
                messy.compact_peeled_address <> messy.peeled_address
                OR canon.compact_peeled_address <> canon.peeled_address
            )
        """

        steps.extend(
            [
                CTEStep("messy_residual", messy_residual_sql),
                CTEStep("residual_postcodes", residual_postcodes_sql),
                CTEStep("canonical_residual", canonical_residual_sql),
                CTEStep("stripped_messy", stripped_messy_sql),
                CTEStep("stripped_canonical", stripped_canonical_sql),
                CTEStep("stripped_candidates", stripped_candidates_sql),
            ]
        )

        final_matches_sql = """
            SELECT * FROM {pre_stripped_matches}
            UNION ALL
            SELECT * FROM {stripped_candidates}
        """
    else:
        final_matches_sql = "SELECT * FROM {pre_stripped_matches}"

    steps.append(CTEStep("peeled_address_matches", final_matches_sql))
    return steps


def _normalise_end_token(token: str) -> str:
    return " ".join(token.strip().upper().split())


@lru_cache(maxsize=1)
def _load_end_tokens_for_regex() -> tuple[str, ...]:
    data_path = files("uk_address_matcher.data").joinpath("common_uk_end_tokens.json")
    data = json.loads(data_path.read_text(encoding="utf-8"))

    aliases = data.get("aliases", {}) or {}
    candidates = (
        list(data.get("single_tokens", []) or [])
        + list(data.get("multi_tokens", []) or [])
        + list(aliases.keys())
        + list(aliases.values())
    )

    seen: set[str] = set()
    ordered: list[str] = []
    for value in candidates:
        if not isinstance(value, str):
            continue
        token = _normalise_end_token(value)
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)

    ordered.sort(key=lambda token: (-len(token.split()), -len(token), token))
    return tuple(ordered)


@lru_cache(maxsize=1)
def _build_suffix_peel_regex_sql_literal() -> str:
    tokens = _load_end_tokens_for_regex()
    escaped = "|".join(re.escape(token).replace(r"\ ", " ") for token in tokens)
    pattern = rf"(?:^|\s+)(?:{escaped})(?:\s+(?:{escaped}))*\s*$"
    return pattern.replace("'", "''")


def _compacted_address_sql(expression: str) -> str:
    return rf"regexp_replace({expression}, '[^A-Z0-9]+', '', 'g')"


def _build_regex_peel_sql(
    *,
    source_placeholder: str,
    id_column: str,
    canonical: bool,
) -> str:
    pattern_sql = _build_suffix_peel_regex_sql_literal()

    if canonical:
        return f"""
            WITH normalised AS (
                SELECT
                    {id_column} AS canonical_ukam_address_id,
                    canonical_unique_id,
                    postcode,
                    regexp_replace(
                        upper(trim(clean_full_address)),
                        '\\s+',
                        ' ',
                        'g'
                    ) AS canonical_clean_full_address
                FROM {{{source_placeholder}}}
            ),
            peeled AS (
                SELECT
                    canonical_ukam_address_id,
                    canonical_unique_id,
                    postcode,
                    canonical_clean_full_address,
                    trim(
                        regexp_replace(
                            canonical_clean_full_address,
                            '{pattern_sql}',
                            ''
                        )
                    ) AS peeled_address
                FROM normalised
            )
            SELECT
                canonical_ukam_address_id,
                canonical_unique_id,
                postcode,
                canonical_clean_full_address,
                peeled_address,
                peeled_address <> canonical_clean_full_address AS did_peel
            FROM peeled
        """

    return f"""
        WITH normalised AS (
            SELECT
                {id_column} AS ukam_address_id,
                postcode,
                regexp_replace(
                    upper(trim(clean_full_address)),
                    '\\s+',
                    ' ',
                    'g'
                ) AS clean_full_address
            FROM {{{source_placeholder}}}
        ),
        peeled AS (
            SELECT
                ukam_address_id,
                postcode,
                clean_full_address,
                trim(
                    regexp_replace(
                        clean_full_address,
                        '{pattern_sql}',
                        ''
                    )
                ) AS peeled_address
            FROM normalised
        )
        SELECT
            ukam_address_id,
            postcode,
            clean_full_address,
            peeled_address,
            peeled_address <> clean_full_address AS did_peel
        FROM peeled
    """
