from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb


def build_run_totals(
    con: duckdb.DuckDBPyConnection,
    accuracy_relation: duckdb.DuckDBPyRelation,
    *,
    total_input_rows: int,
    total_runtime_seconds: float,
) -> duckdb.DuckDBPyRelation:
    """Build benchmark run totals from the overall row of accuracy output."""
    return con.sql(
        f"""
        SELECT
            {total_input_rows}::BIGINT AS total_input_rows,
            rows_matched_in_stage AS matched_rows,
            ROUND(
                100.0 * rows_matched_in_stage::DOUBLE / NULLIF({total_input_rows}, 0),
                2
            ) AS matched_pct,
            correct_matches,
            wrong_matches AS mismatched_matches,
            wrong_match_rate AS mismatched_of_matched_pct,
            correct_share_of_total AS correct_of_input_pct,
            ROUND(
                100.0 * wrong_matches::DOUBLE / NULLIF({total_input_rows}, 0),
                2
            ) AS mismatched_of_input_pct,
            ROUND({total_runtime_seconds}, 2) AS total_runtime_s
        FROM ({accuracy_relation.sql_query()}) AS accuracy
        WHERE stage = 'overall'
        """
    )
