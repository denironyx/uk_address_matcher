from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from benchmarking.comparisons.comparison_artifacts import (
    build_accuracy_compact_table_sql,
    build_stage_diagnostics_compact_table_sql,
)
from benchmarking.insights.types import BenchmarkComparisonSummary


def _show_json_rows_as_table(
    *,
    con: duckdb.DuckDBPyConnection,
    title: str,
    json_path: str | None,
    baseline_run_timestamp: str | None = None,
    comparison_run_timestamp: str | None = None,
) -> None:
    if not json_path:
        print(f"\n{title}: unavailable")
        return

    path = json_path.replace("'", "''")
    print(f"\n{title}:")
    relation = con.sql(f"SELECT * FROM read_json_auto('{path}')")
    columns = set(relation.columns)

    if {
        "stage",
        "run_type",
        "correct_matches",
        "f1",
        "precision",
        "recall",
    }.issubset(columns):
        con.sql(
            build_accuracy_compact_table_sql(
                json_path=json_path,
                baseline_run_timestamp=baseline_run_timestamp,
                comparison_run_timestamp=comparison_run_timestamp,
            )
        ).show(max_width=50000)
        return

    if {
        "stage",
        "run_type",
        "rows_entering_stage",
        "rows_matched_in_stage",
        "stage_match_rate",
        "elapsed_seconds",
    }.issubset(columns):
        con.sql(
            build_stage_diagnostics_compact_table_sql(
                json_path=json_path,
                baseline_run_timestamp=baseline_run_timestamp,
                comparison_run_timestamp=comparison_run_timestamp,
            )
        ).show(max_width=50000)
        return

    relation.show(max_width=50000)


def _format_run_timestamp(value: str | None) -> str:
    if not value:
        return "unknown"

    normalised = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return value

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    utc_time = parsed.astimezone(UTC)
    return utc_time.strftime("%Y-%m-%d %H:%M:%S UTC")


def _lookup_run_timestamps(
    *,
    history_path: str | None,
    baseline_hash: str,
    comparison_hash: str,
) -> tuple[str | None, str | None]:
    if not history_path:
        return (None, None)

    path = Path(history_path)
    if not path.exists():
        return (None, None)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (None, None)

    runs_by_hash = payload.get("runs_by_hash", {})
    baseline = runs_by_hash.get(baseline_hash, {})
    comparison = runs_by_hash.get(comparison_hash, {})
    return (
        baseline.get("created_at_utc"),
        comparison.get("created_at_utc"),
    )


def print_comparison_report(
    *,
    comparison: BenchmarkComparisonSummary,
    history_path: str | None = None,
) -> None:
    display_con = duckdb.connect(database=":memory:")
    baseline_ts_raw, comparison_ts_raw = _lookup_run_timestamps(
        history_path=history_path,
        baseline_hash=comparison.baseline_hash,
        comparison_hash=comparison.current_hash,
    )
    baseline_ts = _format_run_timestamp(baseline_ts_raw)
    comparison_ts = _format_run_timestamp(comparison_ts_raw)

    print("Comparison completed")
    print(f"- current_hash: {comparison.current_hash}")
    print(f"- baseline_hash: {comparison.baseline_hash}")
    print(f"- summary: {comparison.summary_path}")
    if comparison.chart_paths:
        print("- charts:")
        for chart_path in comparison.chart_paths:
            print(f"  - {chart_path}")

    _show_json_rows_as_table(
        con=display_con,
        title="Accuracy comparison table",
        json_path=comparison.accuracy_comparison_path,
        baseline_run_timestamp=baseline_ts,
        comparison_run_timestamp=comparison_ts,
    )
    _show_json_rows_as_table(
        con=display_con,
        title="Stage diagnostics comparison table",
        json_path=comparison.stage_diagnostics_comparison_path,
        baseline_run_timestamp=baseline_ts,
        comparison_run_timestamp=comparison_ts,
    )
