from __future__ import annotations

import json
from collections.abc import Sequence
from os import PathLike
from pathlib import Path
from typing import Any

_OVERLAY_COLOUR_RANGE = [
    "#4C78A8",
    "#F58518",
    "#54A24B",
    "#E45756",
    "#72B7B2",
    "#EECA3B",
    "#B279A2",
    "#FF9DA6",
]


def _load_precision_recall_chart_input(
    chart: Any,
) -> dict[str, Any]:
    if isinstance(chart, dict):
        return chart

    if isinstance(chart, (str, PathLike)):
        chart_path = Path(chart)
        with chart_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    to_dict = getattr(chart, "to_dict", None)
    if callable(to_dict):
        chart_definition = to_dict()
        if isinstance(chart_definition, dict):
            return chart_definition

    raise TypeError(
        "precision-recall chart input must be an Altair chart, a path to a "
        "Vega-Lite JSON file, or a Vega-Lite chart definition dict"
    )


def _extract_precision_recall_chart_records(
    chart: Any,
) -> list[dict[str, Any]]:
    chart_definition = _load_precision_recall_chart_input(chart)
    data = chart_definition.get("data", {})
    values = data.get("values")

    if values is None:
        dataset_name = data.get("name")
        if dataset_name is not None:
            values = chart_definition.get("datasets", {}).get(dataset_name)

    if not isinstance(values, list):
        raise ValueError("precision-recall chart must contain inline data values")

    extracted: list[dict[str, Any]] = []
    for row in values:
        if not isinstance(row, dict):
            raise ValueError("precision-recall chart data rows must be objects")

        if "precision" not in row or "recall" not in row:
            raise ValueError(
                "precision-recall chart data rows must contain 'precision' and "
                "'recall' fields"
            )

        precision = row["precision"]
        recall = row["recall"]
        if precision is None or recall is None:
            continue

        extracted.append(
            {
                **row,
                "precision": float(precision),
                "recall": float(recall),
            }
        )

    if not extracted:
        raise ValueError("precision-recall chart must contain at least one data row")

    extracted.sort(key=lambda row: (row["recall"], row["precision"]))
    return extracted


def _precision_recall_chart_label(
    chart: Any,
    fallback: str,
) -> str:
    if isinstance(chart, (str, PathLike)):
        return Path(chart).stem

    return fallback


def _normalise_comparison_charts(
    comparison_charts: Any | list[Any],
) -> list[Any]:
    if isinstance(comparison_charts, list):
        charts = comparison_charts
    else:
        charts = [comparison_charts]

    if not charts:
        raise ValueError("comparison_charts must contain at least one chart")

    return charts


def _normalise_comparison_labels(
    comparison_charts: list[Any],
    comparison_labels: str | Sequence[str] | None,
) -> list[str]:
    if comparison_labels is None:
        return [
            _precision_recall_chart_label(chart, f"Comparison {index + 1}")
            for index, chart in enumerate(comparison_charts)
        ]

    if isinstance(comparison_labels, str):
        if len(comparison_charts) != 1:
            raise ValueError(
                "comparison_labels must provide one label per comparison chart"
            )
        return [comparison_labels]

    labels = list(comparison_labels)
    if len(labels) != len(comparison_charts):
        raise ValueError("comparison_labels must provide one label per comparison chart")
    return labels


def _build_curve_records(
    chart: Any,
    *,
    series_id: str,
    series_label: str,
    is_baseline: bool,
) -> list[dict[str, Any]]:
    return [
        {
            **record,
            "series_id": series_id,
            "series_label": series_label,
            "is_baseline": is_baseline,
        }
        for record in _extract_precision_recall_chart_records(chart)
    ]


def _choose_label_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    return max(records, key=lambda row: (row["recall"], row["precision"]))


def _interpolate_precision_for_recall(
    records: list[dict[str, Any]],
    *,
    target_recall: float,
) -> float:
    candidate_precisions: list[float] = []

    for left, right in zip(records, records[1:]):
        left_recall = float(left["recall"])
        right_recall = float(right["recall"])
        lower_recall = min(left_recall, right_recall)
        upper_recall = max(left_recall, right_recall)
        if not (lower_recall <= target_recall <= upper_recall):
            continue

        left_precision = float(left["precision"])
        right_precision = float(right["precision"])

        if left_recall == right_recall:
            clamped_precision = min(
                max(left_precision, min(left_precision, right_precision)),
                max(left_precision, right_precision),
            )
            candidate_precisions.append(clamped_precision)
            continue

        interpolation_fraction = (target_recall - left_recall) / (
            right_recall - left_recall
        )
        candidate_precisions.append(
            left_precision + interpolation_fraction * (right_precision - left_precision)
        )

    if candidate_precisions:
        return candidate_precisions[0]

    nearest_record = min(
        records,
        key=lambda record: abs(float(record["recall"]) - target_recall),
    )
    return float(nearest_record["precision"])


def _build_diff_records(
    baseline_records: list[dict[str, Any]],
    comparison_records_by_label: list[tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    diff_records: list[dict[str, Any]] = []

    for comparison_label, comparison_records in comparison_records_by_label:
        for baseline_record in baseline_records:
            baseline_recall = float(baseline_record["recall"])
            baseline_precision = float(baseline_record["precision"])
            comparison_precision = _interpolate_precision_for_recall(
                comparison_records,
                target_recall=baseline_recall,
            )
            diff_records.append(
                {
                    "baseline_recall": baseline_recall,
                    "baseline_precision": baseline_precision,
                    "comparison_label": comparison_label,
                    "comparison_precision": comparison_precision,
                    "precision_gap_percentage_points": (
                        comparison_precision - baseline_precision
                    )
                    * 100.0,
                    "baseline_truth_threshold": baseline_record.get("truth_threshold"),
                    "baseline_match_probability": baseline_record.get(
                        "match_probability"
                    ),
                }
            )

    return diff_records


def _build_overlay_chart_definition(
    curve_records: list[dict[str, Any]],
    diff_records: list[dict[str, Any]],
    label_records: list[dict[str, Any]],
) -> dict[str, Any]:
    top_panel = {
        "width": 620,
        "height": 320,
        "data": {"values": curve_records},
        "layer": [
            {
                "mark": {
                    "type": "line",
                    "strokeWidth": 2.5,
                    "point": {
                        "filled": True,
                        "size": 36,
                    },
                },
                "encoding": {
                    "x": {
                        "field": "recall",
                        "type": "quantitative",
                        "title": "Recall",
                        "axis": {"format": ".1%"},
                        "scale": {"domain": [0, 1]},
                    },
                    "y": {
                        "field": "precision",
                        "type": "quantitative",
                        "title": "Precision",
                        "axis": {"format": ".1%"},
                        "scale": {"zero": False},
                    },
                    "order": {
                        "field": "recall",
                        "type": "quantitative",
                    },
                    "color": {
                        "field": "series_label",
                        "type": "nominal",
                        "title": "Curve",
                        "scale": {"range": _OVERLAY_COLOUR_RANGE},
                    },
                    "strokeDash": {
                        "field": "is_baseline",
                        "type": "nominal",
                        "legend": None,
                        "scale": {
                            "domain": [True, False],
                            "range": [[1, 0], [6, 3]],
                        },
                    },
                    "tooltip": [
                        {
                            "field": "series_label",
                            "type": "nominal",
                            "title": "Curve",
                        },
                        {
                            "field": "truth_threshold",
                            "type": "quantitative",
                            "title": "Match weight threshold",
                            "format": ".2f",
                        },
                        {
                            "field": "match_probability",
                            "type": "quantitative",
                            "title": "Match probability",
                            "format": ".4f",
                        },
                        {
                            "field": "precision",
                            "type": "quantitative",
                            "title": "Precision",
                            "format": ".2%",
                        },
                        {
                            "field": "recall",
                            "type": "quantitative",
                            "title": "Recall",
                            "format": ".2%",
                        },
                    ],
                },
            },
            {
                "data": {"values": label_records},
                "mark": {
                    "type": "text",
                    "align": "left",
                    "baseline": "middle",
                    "dx": 7,
                    "fontSize": 11,
                    "fontWeight": "bold",
                },
                "encoding": {
                    "x": {
                        "field": "recall",
                        "type": "quantitative",
                    },
                    "y": {
                        "field": "precision",
                        "type": "quantitative",
                    },
                    "text": {
                        "field": "series_label",
                        "type": "nominal",
                    },
                    "color": {
                        "field": "series_label",
                        "type": "nominal",
                        "legend": None,
                        "scale": {"range": _OVERLAY_COLOUR_RANGE},
                    },
                },
            },
        ],
    }

    bottom_panel = {
        "width": 620,
        "height": 180,
        "data": {"values": diff_records},
        "layer": [
            {
                "mark": {
                    "type": "rule",
                    "color": "#9AA1A6",
                    "strokeDash": [4, 4],
                },
                "encoding": {
                    "y": {"datum": 0},
                },
            },
            {
                "mark": {
                    "type": "line",
                    "strokeWidth": 2,
                    "point": {
                        "filled": True,
                        "size": 34,
                    },
                },
                "encoding": {
                    "x": {
                        "field": "baseline_recall",
                        "type": "quantitative",
                        "title": "Baseline recall",
                        "axis": {"format": ".1%"},
                        "scale": {"domain": [0, 1]},
                    },
                    "y": {
                        "field": "precision_gap_percentage_points",
                        "type": "quantitative",
                        "title": "Precision gap (percentage points)",
                        "axis": {"format": "+.2f"},
                    },
                    "order": {
                        "field": "baseline_recall",
                        "type": "quantitative",
                    },
                    "color": {
                        "field": "comparison_label",
                        "type": "nominal",
                        "title": "Comparison",
                        "scale": {"range": _OVERLAY_COLOUR_RANGE[1:]},
                    },
                    "tooltip": [
                        {
                            "field": "comparison_label",
                            "type": "nominal",
                            "title": "Comparison",
                        },
                        {
                            "field": "baseline_precision",
                            "type": "quantitative",
                            "title": "Baseline precision",
                            "format": ".2%",
                        },
                        {
                            "field": "baseline_recall",
                            "type": "quantitative",
                            "title": "Baseline recall",
                            "format": ".2%",
                        },
                        {
                            "field": "comparison_precision",
                            "type": "quantitative",
                            "title": "Interpolated comparison precision",
                            "format": ".2%",
                        },
                        {
                            "field": "precision_gap_percentage_points",
                            "type": "quantitative",
                            "title": "Precision gap (percentage points)",
                            "format": "+.2f",
                        },
                    ],
                },
            },
        ],
    }

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.1.0.json",
        "description": "Overlayed precision-recall curves with recall-aligned precision gaps",
        "title": "Precision-Recall Curve Comparison",
        "padding": {"top": 5, "left": 5, "right": 5, "bottom": 5},
        "vconcat": [
            top_panel,
            bottom_panel,
        ],
        "resolve": {
            "scale": {
                "color": "independent",
            }
        },
        "config": {
            "view": {"stroke": None},
            "axis": {"labelFontSize": 11, "titleFontSize": 12},
            "legend": {"labelFontSize": 11, "titleFontSize": 12},
        },
    }


def _overlay_precision_recall_charts(
    baseline_chart: Any,
    comparison_charts: Any | list[Any],
    *,
    baseline_label: str | None = None,
    comparison_labels: str | Sequence[str] | None = None,
) -> Any:
    normalised_comparison_charts = _normalise_comparison_charts(comparison_charts)
    normalised_comparison_labels = _normalise_comparison_labels(
        normalised_comparison_charts,
        comparison_labels,
    )

    baseline_series_label = baseline_label or "baseline"
    baseline_records = _build_curve_records(
        baseline_chart,
        series_id="baseline",
        series_label=baseline_series_label,
        is_baseline=True,
    )

    curve_records = list(baseline_records)
    label_records = [_choose_label_record(baseline_records)]
    comparison_records_by_label: list[tuple[str, list[dict[str, Any]]]] = []

    for index, (chart, label) in enumerate(
        zip(normalised_comparison_charts, normalised_comparison_labels, strict=True),
        start=1,
    ):
        comparison_records = _build_curve_records(
            chart,
            series_id=f"comparison_{index}",
            series_label=label,
            is_baseline=False,
        )
        curve_records.extend(comparison_records)
        label_records.append(_choose_label_record(comparison_records))
        comparison_records_by_label.append((label, comparison_records))

    diff_records = _build_diff_records(baseline_records, comparison_records_by_label)
    chart_definition = _build_overlay_chart_definition(
        curve_records,
        diff_records,
        label_records,
    )

    try:
        import altair as alt
    except ImportError:
        return chart_definition

    return alt.VConcatChart.from_dict(chart_definition)
