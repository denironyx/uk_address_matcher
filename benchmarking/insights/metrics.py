from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb


def _scored_matches_sql(relation_name: str) -> str:
    return f"""
        SELECT
            match_reason IS NOT NULL AS is_matched,
            (
                CAST(ukam_label AS VARCHAR)
                = CAST(resolved_canonical_id AS VARCHAR)
            ) AS is_correct,
            COALESCE(CAST(match_reason AS VARCHAR), 'unmatched') AS reason_key
        FROM {relation_name}
    """


def summarise_precision_recall(
    con: duckdb.DuckDBPyConnection,
    relation_name: str,
) -> duckdb.DuckDBPyRelation:
    scored_sql = _scored_matches_sql(relation_name)
    return con.sql(
        f"""
        WITH scored AS (
            {scored_sql}
        )
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN is_matched THEN 1 ELSE 0 END) AS matched_rows,
            SUM(CASE WHEN is_matched AND is_correct THEN 1 ELSE 0 END) AS correct_matches,
            ROUND(
                SUM(CASE WHEN is_matched AND is_correct THEN 1 ELSE 0 END)::DOUBLE
                / NULLIF(SUM(CASE WHEN is_matched THEN 1 ELSE 0 END), 0),
                6
            ) AS precision,
            ROUND(
                SUM(CASE WHEN is_matched AND is_correct THEN 1 ELSE 0 END)::DOUBLE
                / NULLIF(COUNT(*), 0),
                6
            ) AS recall
        FROM scored
        """
    )


def summarise_by_match_reason(
    con: duckdb.DuckDBPyConnection,
    relation_name: str,
    match_metrics_relation: duckdb.DuckDBPyRelation,
) -> duckdb.DuckDBPyRelation:
    scored_sql = _scored_matches_sql(relation_name)
    return con.sql(
        """
        WITH scored AS (
            {scored_sql}
        ),
        reason_correctness AS (
            SELECT
                reason_key,
                SUM(CASE WHEN reason_key != 'unmatched' AND is_correct THEN 1 ELSE 0 END)
                    AS correct_matches,
                SUM(CASE WHEN reason_key != 'unmatched' THEN 1 ELSE 0 END)
                    AS matched_rows
            FROM scored
            GROUP BY 1
        ),
        match_metrics AS (
            SELECT
                COALESCE(CAST(match_reason AS VARCHAR), 'unmatched') AS reason_key,
                CAST(match_count AS BIGINT) AS matched_rows,
                REPLACE(CAST(match_percentage AS VARCHAR), '%', '')::DOUBLE
                    AS matched_pct
            FROM ({match_metrics_sql})
        ),
        totals AS (
            SELECT COUNT(*) AS total_rows
            FROM scored
        )
        SELECT
            CASE
                WHEN mm.reason_key = 'unmatched' THEN 'UNMATCHED'
                ELSE mm.reason_key
            END AS match_reason,
            (SELECT total_rows FROM totals) AS total_rows,
            mm.matched_rows,
            ROUND(mm.matched_pct, 2) AS matched_pct,
            COALESCE(rc.correct_matches, 0) AS correct_matches,
            ROUND(
                COALESCE(rc.correct_matches, 0)::DOUBLE
                / NULLIF(mm.matched_rows, 0),
                6
            ) AS precision,
            ROUND(
                COALESCE(rc.correct_matches, 0)::DOUBLE
                / NULLIF((SELECT total_rows FROM totals), 0),
                6
            ) AS recall
        FROM match_metrics AS mm
        LEFT JOIN reason_correctness AS rc
          ON mm.reason_key = rc.reason_key
        ORDER BY
            CASE
                WHEN mm.reason_key = 'unmatched'
                THEN 1
                ELSE 0
            END,
            mm.matched_rows DESC,
            mm.reason_key
        """.format(
            scored_sql=scored_sql,
            match_metrics_sql=match_metrics_relation.sql_query(),
        )
    )


def summarise_run_totals(
    con: duckdb.DuckDBPyConnection,
    relation_name: str,
    total_runtime_seconds: float,
) -> duckdb.DuckDBPyRelation:
    scored_sql = _scored_matches_sql(relation_name)
    return con.sql(
        f"""
        WITH scored AS (
            {scored_sql}
        )
        SELECT
            COUNT(*) AS total_input_rows,
            SUM(CASE WHEN is_matched THEN 1 ELSE 0 END) AS matched_rows,
            ROUND(
                100.0 * SUM(CASE WHEN is_matched THEN 1 ELSE 0 END)::DOUBLE
                / NULLIF(COUNT(*), 0),
                2
            ) AS matched_pct,
            SUM(CASE WHEN is_matched AND is_correct THEN 1 ELSE 0 END) AS correct_matches,
            ROUND(
                100.0 * SUM(CASE WHEN is_matched AND is_correct THEN 1 ELSE 0 END)::DOUBLE
                / NULLIF(COUNT(*), 0),
                2
            ) AS correct_of_input_pct,
            ROUND({total_runtime_seconds}, 2) AS total_runtime_s
        FROM scored
        """
    )
