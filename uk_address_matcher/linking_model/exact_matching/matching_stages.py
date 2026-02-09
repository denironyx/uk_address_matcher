from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Iterable, Optional, Union

from uk_address_matcher.linking_model.matching.stages import (
    ExactMatchStage,
    MatchingStage,
    PeeledAddressStage,
    UniqueTrigramStage,
)
from uk_address_matcher.sql_pipeline.helpers import _uid
from uk_address_matcher.sql_pipeline.match_reasons import MatchReason
from uk_address_matcher.sql_pipeline.validation import ColumnSpec, validate_tables

if TYPE_CHECKING:
    import duckdb

    from uk_address_matcher.sql_pipeline.runner import DebugOptions

logger = logging.getLogger("uk_address_matcher")


class StageName(str, Enum):
    """Available deterministic matching stages."""

    EXACT_MATCHES = "exact_matches"
    UNIQUE_TRIGRAM = "unique_trigram"
    PEELED_ADDRESS = "peeled_address"


StageInput = Union[StageName, str, MatchingStage]

_STAGE_REGISTRY: dict[StageName, MatchingStage] = {
    StageName.EXACT_MATCHES: ExactMatchStage(),
    StageName.UNIQUE_TRIGRAM: UniqueTrigramStage(),
    StageName.PEELED_ADDRESS: PeeledAddressStage(),
}

_ALWAYS_ON: tuple[StageName, ...] = (StageName.EXACT_MATCHES,)


def available_deterministic_stages() -> list[StageName]:
    """Get stages that can be enabled via ``enabled_stage_names``."""
    return [stage for stage in _STAGE_REGISTRY if stage not in _ALWAYS_ON]


def _stage_name_for_instance(stage: MatchingStage) -> str:
    if isinstance(stage, ExactMatchStage):
        return StageName.EXACT_MATCHES.value
    if isinstance(stage, UniqueTrigramStage):
        return StageName.UNIQUE_TRIGRAM.value
    if isinstance(stage, PeeledAddressStage):
        return StageName.PEELED_ADDRESS.value
    return stage.__class__.__name__.lower()


def _normalise_enabled_stages(
    enabled: Optional[Iterable[StageInput]],
) -> list[tuple[str, MatchingStage]]:
    """Validate and normalise configured stage inputs while preserving order."""
    if enabled is None:
        return []

    out: list[tuple[str, MatchingStage]] = []
    seen: set[str] = set()

    for item in enabled:
        if isinstance(item, MatchingStage):
            stage_name = _stage_name_for_instance(item)
            if stage_name in {s.value for s in _ALWAYS_ON}:
                raise ValueError(
                    f"{stage_name} is always enabled and should not be provided."
                )
            if stage_name in seen:
                raise ValueError(f"Duplicate exact matching stage specified: {stage_name}")
            seen.add(stage_name)
            out.append((stage_name, item))
            continue

        try:
            name = item if isinstance(item, StageName) else StageName(item)
        except ValueError as e:
            allowed = ", ".join(stage.value for stage in available_deterministic_stages())
            raise ValueError(
                f"Unknown exact matching stage: {item!r}. Available stages: {allowed}"
            ) from e

        if name in _ALWAYS_ON:
            raise ValueError(
                f"{name.value} is always enabled and should not be provided."
            )

        if name.value in seen:
            raise ValueError(f"Duplicate exact matching stage specified: {name.value}")

        seen.add(name.value)
        out.append((name.value, _STAGE_REGISTRY[name]))

    return out


def _duckdb_column_type(
    con: duckdb.DuckDBPyConnection,
    relation: duckdb.DuckDBPyRelation,
    column_name: str,
    fallback_type: str,
) -> str:
    rows = con.execute(
        f"DESCRIBE SELECT {column_name} FROM ({relation.sql_query()})"
    ).fetchall()
    if not rows:
        return fallback_type
    return str(rows[0][1])


def _create_results_table(
    con: duckdb.DuckDBPyConnection,
    df_messy_clean: duckdb.DuckDBPyRelation,
    df_canonical_clean: duckdb.DuckDBPyRelation,
    results_table: str,
) -> None:
    has_ukam_label = "ukam_label" in df_messy_clean.columns
    ukam_label_projection = ", messy.ukam_label" if has_ukam_label else ""

    resolved_canonical_type = _duckdb_column_type(
        con=con,
        relation=df_canonical_clean,
        column_name="unique_id",
        fallback_type="VARCHAR",
    )
    canonical_ukam_type = _duckdb_column_type(
        con=con,
        relation=df_canonical_clean,
        column_name="ukam_address_id",
        fallback_type="BIGINT",
    )

    enum_values = str(MatchReason.enum_values())

    con.execute(f"DROP TABLE IF EXISTS {results_table}")
    con.execute(
        f"""
        CREATE TABLE {results_table} AS
        SELECT
            messy.ukam_address_id,
            messy.unique_id
            {ukam_label_projection},
            NULL::{resolved_canonical_type} AS resolved_canonical_id,
            NULL::{canonical_ukam_type} AS canonical_ukam_address_id,
            NULL::ENUM {enum_values} AS match_reason
        FROM ({df_messy_clean.sql_query()}) AS messy
        """
    )


def _get_unmatched(
    con: duckdb.DuckDBPyConnection,
    df_messy_clean: duckdb.DuckDBPyRelation,
    results_table: str,
) -> duckdb.DuckDBPyRelation:
    return con.sql(
        f"""
        SELECT messy.*
        FROM ({df_messy_clean.sql_query()}) AS messy
        INNER JOIN {results_table} AS results
            ON results.ukam_address_id = messy.ukam_address_id
        WHERE results.resolved_canonical_id IS NULL
        """
    )


def _build_final_output(
    con: duckdb.DuckDBPyConnection,
    df_messy_clean: duckdb.DuckDBPyRelation,
    df_canonical_clean: duckdb.DuckDBPyRelation,
    results_table: str,
) -> duckdb.DuckDBPyRelation:
    results_columns = [
        row[1] for row in con.execute(f"PRAGMA table_info('{results_table}')").fetchall()
    ]

    excluded = {
        "ukam_address_id",
        "unique_id",
        "ukam_label",
        "resolved_canonical_id",
        "canonical_ukam_address_id",
        "match_reason",
    }
    additional_columns = [column for column in results_columns if column not in excluded]
    additional_projection = "".join(
        f",\n            results.{column}" for column in additional_columns
    )

    canonical_projection = []
    if "original_address_concat" in df_canonical_clean.columns:
        canonical_projection.append(
            "canonical.original_address_concat AS original_address_concat_canonical"
        )
    if "postcode" in df_canonical_clean.columns:
        canonical_projection.append("canonical.postcode AS postcode_canonical")

    canonical_projection_sql = ""
    if canonical_projection:
        canonical_projection_sql = ",\n            " + ",\n            ".join(
            canonical_projection
        )

    return con.sql(
        f"""
        SELECT
            messy.unique_id,
            results.resolved_canonical_id,
            messy.* EXCLUDE(unique_id),
            results.canonical_ukam_address_id,
            results.match_reason
            {additional_projection}
            {canonical_projection_sql}
        FROM ({df_messy_clean.sql_query()}) AS messy
        INNER JOIN {results_table} AS results
            ON results.ukam_address_id = messy.ukam_address_id
        LEFT JOIN ({df_canonical_clean.sql_query()}) AS canonical
            ON canonical.ukam_address_id = results.canonical_ukam_address_id
        """
    )


def run_deterministic_match_pass(
    con: duckdb.DuckDBPyConnection,
    df_addresses_to_match: duckdb.DuckDBPyRelation,
    df_addresses_to_search_within: duckdb.DuckDBPyRelation,
    *,
    enabled_stage_names: Optional[Iterable[StageInput]] = None,
    debug_options: Optional[DebugOptions] = None,
    explain: bool = False,
) -> Optional[duckdb.DuckDBPyRelation]:
    """Run deterministic matching stages sequentially and return unified results."""
    validate_tables(
        relations={
            "messy_addresses": df_addresses_to_match,
            "canonical_addresses": df_addresses_to_search_within,
        },
        required=[
            ColumnSpec("unique_id"),
            ColumnSpec("original_address_concat"),
            ColumnSpec("postcode"),
            ColumnSpec("ukam_address_id"),
        ],
    )

    ordered_stages: list[tuple[str, MatchingStage]] = [
        (StageName.EXACT_MATCHES.value, _STAGE_REGISTRY[StageName.EXACT_MATCHES])
    ]
    ordered_stages.extend(_normalise_enabled_stages(enabled_stage_names))

    uid = _uid()
    results_table = f"__ukam_results_{uid}"
    _create_results_table(
        con=con,
        df_messy_clean=df_addresses_to_match,
        df_canonical_clean=df_addresses_to_search_within,
        results_table=results_table,
    )

    for stage_name, stage in ordered_stages:
        unmatched_count = con.execute(
            f"SELECT COUNT(*) FROM {results_table} WHERE resolved_canonical_id IS NULL"
        ).fetchone()[0]

        if unmatched_count == 0:
            logger.info(
                "All records matched; skipping stage '%s' and remaining stages.",
                stage_name,
            )
            break

        logger.info(
            "Running stage '%s' with %d unmatched records...",
            stage_name,
            unmatched_count,
        )

        df_unmatched = _get_unmatched(con, df_addresses_to_match, results_table)

        stage.run(
            con=con,
            stage_name=stage_name,
            results_table=results_table,
            df_unmatched=df_unmatched,
            df_canonical=df_addresses_to_search_within,
            debug_options=debug_options,
            explain=explain,
        )

        if explain:
            continue

        remaining = con.execute(
            f"SELECT COUNT(*) FROM {results_table} WHERE resolved_canonical_id IS NULL"
        ).fetchone()[0]
        matched_this_stage = unmatched_count - remaining
        logger.info(
            "Stage '%s' matched %d records (%d remaining).",
            stage_name,
            matched_this_stage,
            remaining,
        )

    if explain:
        con.execute(f"DROP TABLE IF EXISTS {results_table}")
        return None

    result = _build_final_output(
        con=con,
        df_messy_clean=df_addresses_to_match,
        df_canonical_clean=df_addresses_to_search_within,
        results_table=results_table,
    )

    final_table = f"__ukam_final_matches_{uid}"
    con.execute(f"DROP TABLE IF EXISTS {final_table}")
    result.to_table(final_table)
    final_result = con.table(final_table)

    con.execute(f"DROP TABLE IF EXISTS {results_table}")

    return final_result
