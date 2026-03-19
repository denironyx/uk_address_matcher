from __future__ import annotations

from typing import TYPE_CHECKING

from benchmarking.insights.types import BenchmarkOutputOptions
from uk_address_matcher.post_linkage.match_result.result import MatchResult

if TYPE_CHECKING:
    from benchmarking.runner import BenchmarkRunResult


def _show_via_sql(result: BenchmarkRunResult, relation) -> None:
    relation.show(max_width=50000)


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _print_by_match_reason(
    result: BenchmarkRunResult,
    relation,
    *,
    title: str,
    section_header: str,
) -> None:
    reason_rel = result.con.sql(
        f"""
        SELECT DISTINCT match_reason
        FROM ({relation.sql_query()}) AS data
        WHERE match_reason IS NOT NULL
        ORDER BY match_reason
        """
    )
    reasons = reason_rel.fetchall()

    if not reasons:
        print(f"\n{section_header}")
        print(title)
        print("No rows to display.")
        return

    print(f"\n{section_header}")
    print(title)
    for row in reasons:
        reason_name = str(row[0])
        escaped_reason = _sql_literal(reason_name)
        reason_table = result.con.sql(
            f"""
            SELECT * EXCLUDE (match_reason)
            FROM ({relation.sql_query()}) AS data
            WHERE match_reason = '{escaped_reason}'
            """
        )
        row_count = int(reason_table.aggregate("COUNT(*) AS row_count").fetchone()[0])
        print(f"\nmatch_reason: {reason_name}. Showing {row_count} records")
        _show_via_sql(result, reason_table)


def print_benchmark_summary(
    results: list[BenchmarkRunResult],
    *,
    splink_baseline_weight: float | None = None,
    splink_comparison_weights: list[float] | None = None,
) -> None:
    print("\nBenchmark summary")
    for result in results:
        print(f"\nDataset: {result.dataset_key}")

        print(
            "Timings: "
            f"data_load={result.timings['data_load']:.2f}s, "
            f"match_pipeline={result.timings['match_pipeline']:.2f}s"
        )

        if result.accuracy_table is not None:
            print("\nAccuracy table:")
            _show_via_sql(result, result.accuracy_table)

        if result.stage_diagnostics_table is not None:
            print("\nStage diagnostics:")
            _show_via_sql(result, result.stage_diagnostics_table)

        if splink_baseline_weight is not None and splink_comparison_weights is not None:
            table_name = f"simple_bench_matches_{result.dataset_key}"
            relation = result.con.table(table_name)
            comparison_result = MatchResult(_relation=relation, con=result.con)

            print("\nSplink threshold comparison:")
            comparison_output = comparison_result._compare_splink_model_results(
                baseline_match_weight=splink_baseline_weight,
                splink_comparison_weights=splink_comparison_weights,
            )

            if comparison_output.total_input_rows is not None:
                print(
                    "Splink comparison input rows "
                    "(constant across thresholds): "
                    f"{comparison_output.total_input_rows}"
                )

            print("\nSplink headline performance table")
            _show_via_sql(result, comparison_output.headline_table)

            print("\nSplink change-vs-baseline table")
            _show_via_sql(result, comparison_output.delta_table)


def print_diagnostics(
    results: list[BenchmarkRunResult],
    output_options: BenchmarkOutputOptions | None = None,
) -> None:
    output_options = output_options or BenchmarkOutputOptions()

    for result in results:
        diagnostics = result.diagnostics
        if diagnostics is None:
            continue

        print(f"\nDataset diagnostics: {result.dataset_key}")

        if output_options.show_successful_matches:
            _print_by_match_reason(
                result,
                diagnostics.successful_matches,
                title="Diagnostics: 5 random successful matches",
                section_header="---- SUCCESSFUL MATCHES ----",
            )

        if output_options.show_incorrect_matches:
            _print_by_match_reason(
                result,
                diagnostics.incorrect_matches,
                title="Diagnostics: 10 incorrect matches",
                section_header="---- INCORRECT MATCHES ----",
            )

        if output_options.show_similarity_score_checks:
            print("\nDiagnostics: similarity score checks")
            print("\nDiagnostics: 10 incorrect matches with lowest similarity")
            _show_via_sql(result, diagnostics.lowest_similarity_incorrect)
            print("\nDiagnostics: 10 incorrect matches with highest similarity")
            _show_via_sql(result, diagnostics.highest_similarity_incorrect)
            print("\nDiagnostics: suspicious incorrect-match summary")
            _show_via_sql(result, diagnostics.suspicious_incorrect_summary)

        if output_options.show_unmatched_records:
            print("\nDiagnostics: unmatched records with highest Splink comparison")
            if diagnostics.unmatched_top_splink is None:
                if diagnostics.splink_available:
                    print("No Splink candidate rows found for sampled unmatched records.")
                else:
                    print("Splink not active for this run.")
            else:
                _show_via_sql(result, diagnostics.unmatched_top_splink)


def print_results(
    results: list[BenchmarkRunResult],
    output_options: BenchmarkOutputOptions | None = None,
) -> None:
    output_options = output_options or BenchmarkOutputOptions()
    print_benchmark_summary(results)
    if output_options.enable_diagnostics():
        print_diagnostics(results, output_options=output_options)
