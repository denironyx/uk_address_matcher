from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from uk_address_matcher.sql_pipeline.match_reasons import MatchReason

if TYPE_CHECKING:
    import duckdb


@dataclass(frozen=True)
class SplinkModelComparisonOutput:
    """Display-focused Splink threshold comparison output.

    headline_table contains compact per-threshold metrics.
    delta_table contains changes versus baseline.
    total_input_rows is provided for optional title/subtitle display.
    """

    headline_table: duckdb.DuckDBPyRelation
    delta_table: duckdb.DuckDBPyRelation
    total_input_rows: int | None


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def resolve_splink_threshold_match_weight(
    *,
    splink_match_weight_threshold: float | None,
    splink_match_probability_threshold: float | None,
) -> float | None:
    if (
        splink_match_weight_threshold is not None
        and splink_match_probability_threshold is not None
    ):
        raise ValueError(
            "Provide only one of splink_match_weight_threshold or "
            "splink_match_probability_threshold."
        )
    if splink_match_probability_threshold is None:
        return splink_match_weight_threshold
    if not 0.0 <= splink_match_probability_threshold <= 1.0:
        raise ValueError(
            "splink_match_probability_threshold must be between 0.0 and 1.0 inclusive."
        )
    return math.log2(
        splink_match_probability_threshold / (1.0 - splink_match_probability_threshold)
    )


def build_accuracy_table(
    con: duckdb.DuckDBPyConnection,
    relation: duckdb.DuckDBPyRelation,
    *,
    splink_match_weight_threshold: float | None = None,
    splink_match_probability_threshold: float | None = None,
) -> duckdb.DuckDBPyRelation:
    if "ukam_label" not in relation.columns:
        raise ValueError(
            "_accuracy_table requires a 'ukam_label' column in the match results. "
            "Add a ground-truth label column to the input addresses_to_match data."
        )

    # normalise our match weight threshold irrespective of whether it's provided as a
    # weight or probability
    threshold_match_weight = resolve_splink_threshold_match_weight(
        splink_match_weight_threshold=splink_match_weight_threshold,
        splink_match_probability_threshold=splink_match_probability_threshold,
    )
    splink_accepted_sql = (
        "TRUE"
        if threshold_match_weight is None
        else f"COALESCE(m.match_weight, -1000.0) >= {threshold_match_weight}"
    )
    splink_value = _sql_literal(MatchReason.SPLINK.value)
    enum_values = str(MatchReason.enum_values())
    splink_reason_sql = f"'{splink_value}'::ENUM {enum_values}"

    return con.sql(
        f"""
        WITH scored AS (
            SELECT
                CASE
                    WHEN m.match_reason IS NULL THEN 'unmatched'
                    WHEN split_part(m.match_reason::VARCHAR, ':', 1) = 'exact'
                        THEN 'exact_matches'
                    ELSE split_part(m.match_reason::VARCHAR, ':', 1)
                END AS stage,
                CASE
                    WHEN m.match_reason IS NULL THEN FALSE
                    WHEN m.match_reason = {splink_reason_sql} THEN {splink_accepted_sql}
                    ELSE TRUE
                END AS is_matched,
                CASE
                    WHEN m.match_reason IS NULL THEN FALSE
                    WHEN m.match_reason = {splink_reason_sql} THEN {splink_accepted_sql}
                    ELSE TRUE
                END
                AND CAST(m.resolved_canonical_id AS VARCHAR)
                    = CAST(m.ukam_label AS VARCHAR) AS is_correct
            FROM ({relation.sql_query()}) AS m
        ),
        totals AS (
            SELECT COUNT(*) AS total_input_rows FROM scored
        ),
        stage_base AS (
            SELECT
                stage,
                SUM(CASE WHEN is_matched THEN 1 ELSE 0 END) AS rows_matched_in_stage,
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_matches
            FROM scored
            GROUP BY stage
        ),
        overall_base AS (
            SELECT
                'overall' AS stage,
                SUM(CASE WHEN is_matched THEN 1 ELSE 0 END) AS rows_matched_in_stage,
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_matches
            FROM scored
        ),
        all_rows AS (
            SELECT * FROM overall_base
            UNION ALL
            SELECT * FROM stage_base
        )
        SELECT
            stage,
            rows_matched_in_stage,
            correct_matches,
            rows_matched_in_stage - correct_matches AS wrong_matches,
            ROUND(
                correct_matches::DOUBLE / NULLIF(rows_matched_in_stage, 0),
                6
            ) AS precision,
            ROUND(
                100.0 * (rows_matched_in_stage - correct_matches)::DOUBLE
                / NULLIF(rows_matched_in_stage, 0),
                2
            ) AS wrong_match_rate,
            ROUND(
                100.0 * correct_matches::DOUBLE
                / NULLIF((SELECT total_input_rows FROM totals), 0),
                2
            ) AS correct_share_of_total,
            ROUND(
                correct_matches::DOUBLE
                / NULLIF((SELECT total_input_rows FROM totals), 0),
                6
            ) AS recall,
            ROUND(
                CASE
                    WHEN 2.0 * correct_matches::DOUBLE
                        + (rows_matched_in_stage - correct_matches)::DOUBLE
                        + (
                            (SELECT total_input_rows FROM totals)
                            - correct_matches
                        )::DOUBLE = 0
                    THEN 0.0
                    ELSE
                        2.0 * correct_matches::DOUBLE
                        / (
                            2.0 * correct_matches::DOUBLE
                            + (rows_matched_in_stage - correct_matches)::DOUBLE
                            + (
                                (SELECT total_input_rows FROM totals)
                                - correct_matches
                            )::DOUBLE
                        )
                END,
                6
            ) AS f1
        FROM all_rows
        ORDER BY
            rows_matched_in_stage DESC,
            stage
        """
    )


def build_splink_model_comparison(
    con: duckdb.DuckDBPyConnection,
    relation: duckdb.DuckDBPyRelation,
    *,
    splink_comparison_weights: list[float] | None = None,
    baseline_match_weight: float,
) -> SplinkModelComparisonOutput:
    scenario_queries: list[str] = []
    total_input_rows = int(
        con.sql(f"SELECT COUNT(*) FROM ({relation.sql_query()}) AS m").fetchone()[0]
    )

    baseline_value = float(baseline_match_weight)
    baseline_label = f"weight_{baseline_value}"
    baseline_rel = build_accuracy_table(
        con,
        relation,
        splink_match_weight_threshold=baseline_value,
    )
    scenario_queries.append(
        f"""
        SELECT
            0 AS scenario_order,
            '{_sql_literal(baseline_label)}' AS scenario,
            {baseline_value}::DOUBLE AS threshold_match_weight,
            {total_input_rows}::BIGINT AS total_input_rows,
            *
        FROM ({baseline_rel.sql_query()}) AS accuracy
        WHERE stage = 'splink'
        """
    )

    unique_comparison_weights: list[float] = []
    if splink_comparison_weights is not None:
        seen_weights: set[float] = set()
        for weight in splink_comparison_weights:
            weight_value = float(weight)
            if weight_value == baseline_value:
                continue
            if weight_value in seen_weights:
                continue
            seen_weights.add(weight_value)
            unique_comparison_weights.append(weight_value)

    sorted_comparison_weights = sorted(unique_comparison_weights)

    for index, threshold_value in enumerate(sorted_comparison_weights, start=1):
        rel = build_accuracy_table(
            con,
            relation,
            splink_match_weight_threshold=threshold_value,
        )
        scenario_label = f"weight_{threshold_value}"
        scenario_queries.append(
            f"""
            SELECT
                {index} AS scenario_order,
                '{_sql_literal(scenario_label)}' AS scenario,
                {threshold_value}::DOUBLE AS threshold_match_weight,
                {total_input_rows}::BIGINT AS total_input_rows,
                *
            FROM ({rel.sql_query()}) AS accuracy
            WHERE stage = 'splink'
            """
        )

    union_sql = "\nUNION ALL\n".join(q.strip() for q in scenario_queries)
    baseline_literal = _sql_literal(baseline_label)

    base_compared = con.sql(
        f"""
        WITH compared AS (
            {union_sql}
        ),
        baseline_rows AS (
            SELECT
                rows_matched_in_stage AS baseline_matched_rows,
                correct_matches AS baseline_correct_matches,
                precision AS baseline_precision,
                recall AS baseline_recall,
                f1 AS baseline_f1
            FROM compared
            WHERE scenario = '{baseline_literal}'
        )
        SELECT
            c.scenario_order,
            c.scenario,
            c.threshold_match_weight,
            c.total_input_rows,
            c.rows_matched_in_stage,
            c.correct_matches,
            c.wrong_matches,
            c.precision,
            c.recall,
            c.f1,
            c.rows_matched_in_stage - b.baseline_matched_rows AS delta_matched_rows,
            c.correct_matches - b.baseline_correct_matches AS delta_correct_matches,
            c.precision - b.baseline_precision AS delta_precision,
            c.recall - b.baseline_recall AS delta_recall,
            c.f1 - b.baseline_f1 AS delta_f1,
            CASE WHEN c.scenario = '{baseline_literal}' THEN TRUE ELSE FALSE END
                AS is_baseline
        FROM compared AS c
        LEFT JOIN baseline_rows AS b
            ON TRUE
        ORDER BY c.scenario_order, c.threshold_match_weight
        """
    )

    headline_table = con.sql(
        f"""
        WITH compared AS (
            SELECT *
            FROM ({base_compared.sql_query()}) AS c
        )
        SELECT
            CASE
                WHEN is_baseline THEN concat(scenario, ' (baseline)')
                ELSE scenario
            END AS scenario,
            ROUND(threshold_match_weight, 2) AS threshold,
            format('{{:,}}', rows_matched_in_stage) AS matched_rows,
            concat(
                CAST(
                    ROUND(
                        100.0
                        * rows_matched_in_stage::DOUBLE
                        / NULLIF(total_input_rows, 0),
                        1
                    ) AS VARCHAR
                ),
                '%'
            ) AS match_rate,
            format('{{:,}}', correct_matches) AS correct_matches,
            format('{{:,}}', wrong_matches) AS mismatched_matches,
            ROUND(precision, 3) AS precision,
            ROUND(recall, 3) AS recall,
            ROUND(f1, 3) AS f1,
            CASE
                WHEN is_baseline THEN 'Baseline threshold for comparison'
                WHEN delta_matched_rows > 0 AND delta_recall > 0 AND delta_precision < 0
                    THEN 'More matches and higher recall, slight drop in precision'
                WHEN delta_matched_rows < 0 AND delta_precision > 0 AND delta_recall < 0
                    THEN 'Fewer matches, slightly higher precision, lower recall'
                WHEN delta_matched_rows > 0 AND delta_precision >= 0 AND delta_recall >= 0
                    THEN 'More matches with improved precision and recall'
                WHEN delta_matched_rows < 0 AND delta_precision <= 0 AND delta_recall <= 0
                    THEN 'Fewer matches with weaker precision and recall'
                ELSE 'Trade-off requires judgement across precision and recall'
            END AS interpretation
        FROM compared
        ORDER BY scenario_order, threshold
        """
    )

    delta_table = con.sql(
        f"""
        WITH compared AS (
            SELECT *
            FROM ({base_compared.sql_query()}) AS c
        )
        SELECT
            CASE
                WHEN is_baseline THEN concat(scenario, ' (baseline)')
                ELSE scenario
            END AS scenario,
            CASE
                WHEN is_baseline THEN format('{{:,}}', rows_matched_in_stage)
                WHEN delta_matched_rows > 0
                    THEN concat(
                        '+',
                        format('{{:,}}', delta_matched_rows)
                    )
                WHEN delta_matched_rows < 0 THEN format('{{:,}}', delta_matched_rows)
                ELSE '0'
            END AS delta_matched_rows,
            CASE
                WHEN is_baseline THEN format('{{:,}}', correct_matches)
                WHEN delta_correct_matches > 0
                    THEN concat(
                        '+',
                        format('{{:,}}', delta_correct_matches)
                    )
                WHEN delta_correct_matches < 0
                    THEN format('{{:,}}', delta_correct_matches)
                ELSE '0'
            END AS delta_correct_matches,
            CASE
                WHEN is_baseline
                    THEN concat(CAST(ROUND(precision * 100.0, 1) AS VARCHAR), '%')
                WHEN delta_precision > 0
                    THEN concat(
                        '+',
                        CAST(ROUND(delta_precision * 100.0, 1) AS VARCHAR),
                        ' pp'
                    )
                WHEN delta_precision < 0
                    THEN concat(
                        CAST(ROUND(delta_precision * 100.0, 1) AS VARCHAR),
                        ' pp'
                    )
                ELSE '0.0 pp'
            END AS precision_delta,
            CASE
                WHEN is_baseline
                    THEN concat(CAST(ROUND(recall * 100.0, 1) AS VARCHAR), '%')
                WHEN delta_recall > 0
                    THEN concat(
                        '+',
                        CAST(ROUND(delta_recall * 100.0, 1) AS VARCHAR),
                        ' pp'
                    )
                WHEN delta_recall < 0
                    THEN concat(
                        CAST(ROUND(delta_recall * 100.0, 1) AS VARCHAR),
                        ' pp'
                    )
                ELSE '0.0 pp'
            END AS recall_delta,
            CASE
                WHEN is_baseline
                    THEN concat(CAST(ROUND(f1 * 100.0, 1) AS VARCHAR), '%')
                WHEN delta_f1 > 0
                    THEN concat(
                        '+',
                        CAST(ROUND(delta_f1 * 100.0, 1) AS VARCHAR),
                        ' pp'
                    )
                WHEN delta_f1 < 0
                    THEN concat(
                        CAST(ROUND(delta_f1 * 100.0, 1) AS VARCHAR),
                        ' pp'
                    )
                ELSE '0.0 pp'
            END AS f1_delta
        FROM compared
        ORDER BY scenario_order, threshold_match_weight
        """
    )

    total_input_row = con.sql(
        f"""
        SELECT DISTINCT total_input_rows
        FROM ({base_compared.sql_query()}) AS c
        """
    ).fetchall()
    total_input_rows = int(total_input_row[0][0]) if len(total_input_row) == 1 else None

    return SplinkModelComparisonOutput(
        headline_table=headline_table,
        delta_table=delta_table,
        total_input_rows=total_input_rows,
    )
