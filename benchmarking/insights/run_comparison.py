from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarking.insights.types import BenchmarkComparisonSummary

_OVERALL_STAGE = "overall"


def _stage_sort_key(stage: str) -> tuple[int, str]:
    if stage == _OVERALL_STAGE:
        return (0, stage)
    return (1, stage)


def _index_by_stage(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["stage"]): row for row in rows if "stage" in row}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _delta(current: Any, baseline: Any) -> float | None:
    current_f = _to_float(current)
    baseline_f = _to_float(baseline)
    if current_f is None or baseline_f is None:
        return None
    return round(current_f - baseline_f, 8)


def _sql_string_literal(value: str) -> str:
    return value.replace("'", "''")


def build_accuracy_compact_table_sql(*, json_path: str) -> str:
    escaped_path = _sql_string_literal(json_path)
    return f"""
    WITH raw AS (
        SELECT *
        FROM read_json_auto('{escaped_path}')
        WHERE stage IN ('exact_matches', 'peeled_address', 'splink')
    )
    SELECT
        stage,
        CAST(
            max(CASE WHEN run_type = 'baseline' THEN correct_matches END)
            AS BIGINT
        ) AS baseline_correct_matches,
        CAST(
            max(CASE WHEN run_type = 'comparison' THEN correct_matches END)
            AS BIGINT
        ) AS comparison_correct_matches,
        CAST(
            max(CASE WHEN run_type = 'comparison' THEN correct_matches END)
            -
            max(CASE WHEN run_type = 'baseline' THEN correct_matches END)
            AS BIGINT
        ) AS delta_correct_matches,
        round(max(CASE WHEN run_type = 'baseline' THEN precision END), 6)
            AS baseline_precision,
        round(max(CASE WHEN run_type = 'comparison' THEN precision END), 6)
            AS comparison_precision,
        round(
            max(CASE WHEN run_type = 'comparison' THEN precision END)
            - max(CASE WHEN run_type = 'baseline' THEN precision END),
            6
        ) AS delta_precision,
        round(max(CASE WHEN run_type = 'baseline' THEN recall END), 6)
            AS baseline_recall,
        round(max(CASE WHEN run_type = 'comparison' THEN recall END), 6)
            AS comparison_recall,
        round(
            max(CASE WHEN run_type = 'comparison' THEN recall END)
            - max(CASE WHEN run_type = 'baseline' THEN recall END),
            6
        ) AS delta_recall,
        round(max(CASE WHEN run_type = 'baseline' THEN f1 END), 6)
            AS baseline_f1,
        round(max(CASE WHEN run_type = 'comparison' THEN f1 END), 6)
            AS comparison_f1,
        round(
            max(CASE WHEN run_type = 'comparison' THEN f1 END)
            - max(CASE WHEN run_type = 'baseline' THEN f1 END),
            6
        ) AS delta_f1,
        max(CASE WHEN run_type = 'baseline' THEN run_hash END)
            AS baseline_hash,
        max(CASE WHEN run_type = 'comparison' THEN run_hash END)
            AS comparison_hash,
        max(CASE WHEN run_type = 'baseline' THEN git_commit_hash END)
            AS baseline_commit_hash,
        max(CASE WHEN run_type = 'comparison' THEN git_commit_hash END)
            AS comparison_commit_hash
    FROM raw
    GROUP BY stage
    ORDER BY
        CASE stage
            WHEN 'exact_matches' THEN 1
            WHEN 'peeled_address' THEN 2
            WHEN 'splink' THEN 3
            ELSE 99
        END
    """


def build_stage_diagnostics_compact_table_sql(*, json_path: str) -> str:
    escaped_path = _sql_string_literal(json_path)
    return f"""
    WITH raw AS (
        SELECT *
        FROM read_json_auto('{escaped_path}')
        WHERE stage IN ('exact_matches', 'peeled_address', 'splink')
    )
    SELECT
        stage,
        CAST(
            max(CASE WHEN run_type = 'baseline' THEN rows_entering_stage END)
            AS BIGINT
        ) AS baseline_rows_entering_stage,
        CAST(
            max(CASE WHEN run_type = 'comparison' THEN rows_entering_stage END)
            AS BIGINT
        ) AS comparison_rows_entering_stage,
        CAST(
            max(CASE WHEN run_type = 'comparison' THEN rows_entering_stage END)
            - max(CASE WHEN run_type = 'baseline' THEN rows_entering_stage END)
            AS BIGINT
        ) AS delta_rows_entering_stage,
        CAST(
            max(CASE WHEN run_type = 'baseline' THEN rows_matched_in_stage END)
            AS BIGINT
        ) AS baseline_rows_matched_in_stage,
        CAST(
            max(CASE WHEN run_type = 'comparison' THEN rows_matched_in_stage END)
            AS BIGINT
        ) AS comparison_rows_matched_in_stage,
        CAST(
            max(CASE WHEN run_type = 'comparison' THEN rows_matched_in_stage END)
            - max(CASE WHEN run_type = 'baseline' THEN rows_matched_in_stage END)
            AS BIGINT
        ) AS delta_rows_matched_in_stage,
        round(max(CASE WHEN run_type = 'baseline' THEN stage_match_rate END), 6)
            AS baseline_stage_match_rate,
        round(max(CASE WHEN run_type = 'comparison' THEN stage_match_rate END), 6)
            AS comparison_stage_match_rate,
        round(
            max(CASE WHEN run_type = 'comparison' THEN stage_match_rate END)
            - max(CASE WHEN run_type = 'baseline' THEN stage_match_rate END),
            6
        ) AS delta_stage_match_rate,
        round(max(CASE WHEN run_type = 'baseline' THEN elapsed_seconds END), 6)
            AS baseline_elapsed_seconds,
        round(max(CASE WHEN run_type = 'comparison' THEN elapsed_seconds END), 6)
            AS comparison_elapsed_seconds,
        round(
            max(CASE WHEN run_type = 'comparison' THEN elapsed_seconds END)
            - max(CASE WHEN run_type = 'baseline' THEN elapsed_seconds END),
            6
        ) AS delta_elapsed_seconds,
        max(CASE WHEN run_type = 'baseline' THEN run_hash END)
            AS baseline_hash,
        max(CASE WHEN run_type = 'comparison' THEN run_hash END)
            AS comparison_hash,
        max(CASE WHEN run_type = 'baseline' THEN git_commit_hash END)
            AS baseline_commit_hash,
        max(CASE WHEN run_type = 'comparison' THEN git_commit_hash END)
            AS comparison_commit_hash
    FROM raw
    GROUP BY stage
    ORDER BY
        CASE stage
            WHEN 'exact_matches' THEN 1
            WHEN 'peeled_address' THEN 2
            WHEN 'splink' THEN 3
            ELSE 99
        END
    """


def build_accuracy_comparison_rows(
    *,
    baseline_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    baseline_hash: str,
    current_hash: str,
    baseline_git_commit_hash: str | None = None,
    current_git_commit_hash: str | None = None,
) -> list[dict[str, Any]]:
    baseline_index = _index_by_stage(baseline_rows)
    current_index = _index_by_stage(current_rows)
    stages = sorted(set(baseline_index).union(current_index), key=_stage_sort_key)

    rows: list[dict[str, Any]] = []
    for stage in stages:
        baseline = baseline_index.get(stage, {})
        current = current_index.get(stage, {})

        rows.append(
            {
                "run_type": "baseline",
                "run_hash": baseline_hash,
                "git_commit_hash": baseline_git_commit_hash,
                "baseline_hash": baseline_hash,
                "comparison_hash": current_hash,
                "stage": stage,
                "rows_matched_in_stage": _to_int(baseline.get("rows_matched_in_stage")),
                "correct_matches": _to_int(baseline.get("correct_matches")),
                "wrong_matches": _to_int(baseline.get("wrong_matches")),
                "precision": _to_float(baseline.get("precision")),
                "recall": _to_float(baseline.get("recall")),
                "f1": _to_float(baseline.get("f1")),
                "wrong_match_rate": _to_float(baseline.get("wrong_match_rate")),
                "correct_share_of_total": _to_float(
                    baseline.get("correct_share_of_total")
                ),
            }
        )
        rows.append(
            {
                "run_type": "comparison",
                "run_hash": current_hash,
                "git_commit_hash": current_git_commit_hash,
                "baseline_hash": baseline_hash,
                "comparison_hash": current_hash,
                "stage": stage,
                "rows_matched_in_stage": _to_int(current.get("rows_matched_in_stage")),
                "correct_matches": _to_int(current.get("correct_matches")),
                "wrong_matches": _to_int(current.get("wrong_matches")),
                "precision": _to_float(current.get("precision")),
                "recall": _to_float(current.get("recall")),
                "f1": _to_float(current.get("f1")),
                "wrong_match_rate": _to_float(current.get("wrong_match_rate")),
                "correct_share_of_total": _to_float(
                    current.get("correct_share_of_total")
                ),
            }
        )

    return rows


def build_stage_diagnostics_comparison_rows(
    *,
    baseline_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    baseline_hash: str,
    current_hash: str,
    baseline_git_commit_hash: str | None = None,
    current_git_commit_hash: str | None = None,
) -> list[dict[str, Any]]:
    baseline_index = _index_by_stage(baseline_rows)
    current_index = _index_by_stage(current_rows)
    stages = sorted(set(baseline_index).union(current_index), key=_stage_sort_key)

    rows: list[dict[str, Any]] = []
    for stage in stages:
        baseline = baseline_index.get(stage, {})
        current = current_index.get(stage, {})
        rows.append(
            {
                "run_type": "baseline",
                "run_hash": baseline_hash,
                "git_commit_hash": baseline_git_commit_hash,
                "baseline_hash": baseline_hash,
                "comparison_hash": current_hash,
                "stage": stage,
                "stage_order": _to_int(baseline.get("stage_order")),
                "rows_entering_stage": _to_int(baseline.get("rows_entering_stage")),
                "rows_matched_in_stage": _to_int(baseline.get("rows_matched_in_stage")),
                "stage_match_rate": _to_float(baseline.get("stage_match_rate")),
                "share_of_total_input_matched": _to_float(
                    baseline.get("share_of_total_input_matched")
                ),
                "elapsed_seconds": _to_float(baseline.get("elapsed_seconds")),
            }
        )
        rows.append(
            {
                "run_type": "comparison",
                "run_hash": current_hash,
                "git_commit_hash": current_git_commit_hash,
                "baseline_hash": baseline_hash,
                "comparison_hash": current_hash,
                "stage": stage,
                "stage_order": _to_int(current.get("stage_order")),
                "rows_entering_stage": _to_int(current.get("rows_entering_stage")),
                "rows_matched_in_stage": _to_int(current.get("rows_matched_in_stage")),
                "stage_match_rate": _to_float(current.get("stage_match_rate")),
                "share_of_total_input_matched": _to_float(
                    current.get("share_of_total_input_matched")
                ),
                "elapsed_seconds": _to_float(current.get("elapsed_seconds")),
            }
        )

    return rows


def _build_notes(overall_delta: dict[str, float | None]) -> list[str]:
    notes: list[str] = []

    for metric, direction_text in (
        ("precision", "precision"),
        ("recall", "recall"),
        ("f1", "f1"),
    ):
        delta = overall_delta.get(metric)
        if delta is None:
            continue
        if delta > 0:
            notes.append(f"Overall {direction_text} improved by {delta:.4f}.")
        elif delta < 0:
            notes.append(f"Overall {direction_text} regressed by {abs(delta):.4f}.")

    runtime_delta = overall_delta.get("total_runtime_seconds")
    if runtime_delta is not None:
        if runtime_delta < 0:
            notes.append(f"Total runtime improved by {abs(runtime_delta):.3f}s.")
        elif runtime_delta > 0:
            notes.append(f"Total runtime increased by {runtime_delta:.3f}s.")

    if not notes:
        notes.append("No material overall deltas detected.")
    return notes


def build_comparison_summary(
    *,
    baseline_hash: str,
    current_hash: str,
    baseline_accuracy_rows: list[dict[str, Any]],
    current_accuracy_rows: list[dict[str, Any]],
    baseline_stage_rows: list[dict[str, Any]],
    current_stage_rows: list[dict[str, Any]],
    baseline_total_runtime_seconds: float | None,
    current_total_runtime_seconds: float | None,
    summary_path: Path,
    chart_paths: list[Path],
    accuracy_comparison_path: Path | None = None,
    stage_diagnostics_comparison_path: Path | None = None,
) -> BenchmarkComparisonSummary:
    baseline_accuracy = _index_by_stage(baseline_accuracy_rows)
    current_accuracy = _index_by_stage(current_accuracy_rows)
    baseline_stages = _index_by_stage(baseline_stage_rows)
    current_stages = _index_by_stage(current_stage_rows)

    overall_current = current_accuracy.get(_OVERALL_STAGE, {})
    overall_baseline = baseline_accuracy.get(_OVERALL_STAGE, {})
    overall_delta = {
        "precision": _delta(
            overall_current.get("precision"),
            overall_baseline.get("precision"),
        ),
        "recall": _delta(
            overall_current.get("recall"),
            overall_baseline.get("recall"),
        ),
        "f1": _delta(overall_current.get("f1"), overall_baseline.get("f1")),
        "wrong_match_rate": _delta(
            overall_current.get("wrong_match_rate"),
            overall_baseline.get("wrong_match_rate"),
        ),
        "total_runtime_seconds": _delta(
            current_total_runtime_seconds,
            baseline_total_runtime_seconds,
        ),
    }

    all_stages = sorted(set(baseline_stages).union(current_stages))
    stage_deltas: dict[str, dict[str, float | None]] = {}
    for stage in all_stages:
        base_row = baseline_stages.get(stage, {})
        current_row = current_stages.get(stage, {})
        stage_deltas[stage] = {
            "rows_matched_in_stage": _delta(
                current_row.get("rows_matched_in_stage"),
                base_row.get("rows_matched_in_stage"),
            ),
            "stage_match_rate": _delta(
                current_row.get("stage_match_rate"),
                base_row.get("stage_match_rate"),
            ),
            "elapsed_seconds": _delta(
                current_row.get("elapsed_seconds"),
                base_row.get("elapsed_seconds"),
            ),
        }

    summary = BenchmarkComparisonSummary(
        baseline_hash=baseline_hash,
        current_hash=current_hash,
        overall_delta=overall_delta,
        stage_deltas=stage_deltas,
        notes=_build_notes(overall_delta),
        summary_path=summary_path.as_posix(),
        chart_paths=[path.as_posix() for path in chart_paths],
        accuracy_comparison_path=(
            accuracy_comparison_path.as_posix()
            if accuracy_comparison_path is not None
            else None
        ),
        stage_diagnostics_comparison_path=(
            stage_diagnostics_comparison_path.as_posix()
            if stage_diagnostics_comparison_path is not None
            else None
        ),
    )

    summary_path.write_text(
        json.dumps(
            {
                "baseline_hash": summary.baseline_hash,
                "current_hash": summary.current_hash,
                "overall_delta": summary.overall_delta,
                "stage_deltas": summary.stage_deltas,
                "notes": summary.notes,
                "chart_paths": summary.chart_paths,
                "accuracy_comparison_path": summary.accuracy_comparison_path,
                "stage_diagnostics_comparison_path": (
                    summary.stage_diagnostics_comparison_path
                ),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return summary


def write_comparison_chart_html(
    *,
    path: Path,
    title: str,
    labels: list[str],
    baseline_values: list[float | None],
    current_values: list[float | None],
) -> None:
    safe_baseline = [0.0 if value is None else float(value) for value in baseline_values]
    safe_current = [0.0 if value is None else float(value) for value in current_values]

    all_values = [*safe_baseline, *safe_current]
    minimum = min(all_values) if all_values else 0.0
    maximum = max(all_values) if all_values else 1.0
    spread = max(maximum - minimum, 0.0001)
    zoom_padding = spread * 0.25
    zoom_min = minimum - zoom_padding
    zoom_max = maximum + zoom_padding

    deltas = [
        round(current - baseline, 8)
        for baseline, current in zip(safe_baseline, safe_current)
    ]

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  <script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
  <style>
        body {{
            font-family: ui-sans-serif, -apple-system, Segoe UI, sans-serif;
            margin: 24px;
        }}
        .card {{ max-width: 1080px; margin: 0 auto; }}
    h1 {{ margin-bottom: 12px; }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }}
        .subtle {{ color: #4b5563; margin: 0; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>{title}</h1>
        <p class=\"subtle\">Overlaid series with shaded difference and zoomed inset.</p>
        <div class=\"grid\">
            <canvas id=\"chart\" height=\"260\"></canvas>
            <canvas id=\"zoomChart\" height=\"170\"></canvas>
        </div>
  </div>
  <script>
    const labels = {json.dumps(labels)};
    const baseline = {json.dumps(safe_baseline)};
    const current = {json.dumps(safe_current)};
        const deltas = {json.dumps(deltas)};

    new Chart(document.getElementById('chart'), {{
            type: 'line',
      data: {{
        labels,
        datasets: [
                    {{
                        label: 'Baseline',
                        data: baseline,
                        borderColor: '#5f6b7a',
                        backgroundColor: 'rgba(95, 107, 122, 0.18)',
                        pointRadius: 3,
                        borderWidth: 2,
                        tension: 0.25
                    }},
                    {{
                        label: 'Comparison',
                        data: current,
                        borderColor: '#1f8a70',
                        backgroundColor: 'rgba(31, 138, 112, 0.28)',
                        pointRadius: 3,
                        borderWidth: 2,
                        tension: 0.25,
                        fill: '-1'
                    }}
        ]
      }},
      options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
                plugins: {{
                    tooltip: {{
                        callbacks: {{
                            afterBody: (ctx) => {{
                                const i = ctx[0].dataIndex;
                                const sign = deltas[i] >= 0 ? '+' : '';
                                return `delta: ${{sign}}${{deltas[i]}}`;
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{ beginAtZero: false }}
                }}
            }}
        }});

        new Chart(document.getElementById('zoomChart'), {{
            type: 'line',
            data: {{
                labels,
                datasets: [
                    {{
                        label: 'Baseline (zoom)',
                        data: baseline,
                        borderColor: '#5f6b7a',
                        backgroundColor: 'rgba(95, 107, 122, 0.08)',
                        pointRadius: 2,
                        borderWidth: 2,
                        tension: 0.2
                    }},
                    {{
                        label: 'Comparison (zoom)',
                        data: current,
                        borderColor: '#1f8a70',
                        backgroundColor: 'rgba(31, 138, 112, 0.16)',
                        pointRadius: 2,
                        borderWidth: 2,
                        tension: 0.2,
                        fill: '-1'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                interaction: {{ mode: 'index', intersect: false }},
                scales: {{
                    y: {{
                        min: {zoom_min},
                        max: {zoom_max}
                    }}
                }}
      }}
    }});
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
