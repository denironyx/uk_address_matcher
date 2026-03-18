from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def build_stage_diagnostics_relation(
    con: duckdb.DuckDBPyConnection,
    stage_diagnostics: list[dict[str, int | float | str]] | None,
) -> duckdb.DuckDBPyRelation:
    if not stage_diagnostics:
        return con.sql(
            """
            SELECT
                CAST(NULL AS VARCHAR) AS stage,
                CAST(NULL AS BIGINT) AS stage_order,
                CAST(NULL AS BIGINT) AS rows_entering_stage,
                CAST(NULL AS BIGINT) AS rows_matched_in_stage,
                CAST(NULL AS DOUBLE) AS stage_match_rate,
                CAST(NULL AS DOUBLE) AS share_of_total_input_matched,
                CAST(NULL AS DOUBLE) AS elapsed_seconds
            WHERE FALSE
            """
        )

    values = []
    for index, row in enumerate(stage_diagnostics):
        stage = _sql_literal(str(row.get("stage", "unknown")))
        unmatched_before = int(row.get("unmatched_before", 0))
        matched_this_stage = int(row.get("matched_this_stage", 0))
        remaining_after = int(row.get("remaining_after", 0))
        matched_pct_of_unmatched = float(row.get("matched_pct_of_unmatched", 0.0))
        matched_pct_of_input = float(row.get("matched_pct_of_input", 0.0))
        elapsed_seconds = float(row.get("elapsed_seconds", 0.0))
        values.append(
            "("
            f"'{stage}', {index}, {unmatched_before}, {matched_this_stage}, "
            f"{remaining_after}, {matched_pct_of_unmatched}, "
            f"{matched_pct_of_input}, {elapsed_seconds}"
            ")"
        )

    values_sql = ",\n                ".join(values)
    return con.sql(
        f"""
        SELECT
            v.stage,
            v.stage_order,
            v.unmatched_before AS rows_entering_stage,
            v.matched_this_stage AS rows_matched_in_stage,
            v.matched_pct_of_unmatched AS stage_match_rate,
            v.matched_pct_of_input AS share_of_total_input_matched,
            v.elapsed_seconds
        FROM (
            VALUES
                {values_sql}
        ) AS v(
            stage,
            stage_order,
            unmatched_before,
            matched_this_stage,
            remaining_after,
            matched_pct_of_unmatched,
            matched_pct_of_input,
            elapsed_seconds
        )
        """
    )


def build_stage_diagnostics_table(
    con: duckdb.DuckDBPyConnection,
    stage_diagnostics_relation: duckdb.DuckDBPyRelation,
) -> duckdb.DuckDBPyRelation:
    return con.sql(
        f"""
        WITH base_rows AS (
            SELECT
                d.stage_order,
                d.stage,
                d.rows_entering_stage,
                d.rows_matched_in_stage,
                ROUND(100.0 * d.stage_match_rate, 2) AS stage_match_rate,
                ROUND(100.0 * d.share_of_total_input_matched, 2)
                    AS share_of_total_input_matched,
                ROUND(d.elapsed_seconds, 4) AS elapsed_seconds
            FROM ({stage_diagnostics_relation.sql_query()}) AS d
        )
        SELECT
            stage_order,
            stage,
            rows_entering_stage,
            rows_matched_in_stage,
            stage_match_rate,
            share_of_total_input_matched,
            elapsed_seconds
        FROM base_rows
        ORDER BY stage_order
        """
    )
