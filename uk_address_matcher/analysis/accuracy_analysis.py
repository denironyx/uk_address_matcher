from __future__ import annotations

import json
from importlib.resources import files
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    import duckdb


def _load_chart_definition(file_name: str) -> dict[str, Any]:
    chart_path = files("uk_address_matcher.analysis.chart_defs").joinpath(file_name)
    with chart_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _visual_chart_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return records used for chart rendering, excluding sentinel thresholds."""
    filtered: list[dict[str, Any]] = []
    for row in records:
        threshold = row.get("truth_threshold")
        if threshold is None:
            filtered.append(row)
            continue
        threshold_value = float(threshold)
        if abs(threshold_value) >= 900:
            continue
        filtered.append(row)
    return filtered


def build_precision_recall_chart_definition(
    records: list[dict[str, Any]],
    add_metrics: list[str] | None = None,
) -> dict[str, Any]:
    del add_metrics
    plot_records = _visual_chart_records(records)
    chart = _load_chart_definition("precision_recall.json")
    chart["data"]["values"] = plot_records
    if chart.get("params"):
        chart["params"][0]["name"] = f"grid_{uuid4().hex}"
    return chart


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

        extracted.append(dict(row))

    return extracted


def _precision_recall_chart_label(
    chart: Any,
    fallback: str,
) -> str:
    if isinstance(chart, (str, PathLike)):
        return Path(chart).stem

    return fallback


def _overlay_precision_recall_charts(
    first_chart: Any,
    second_chart: Any,
    *,
    first_label: str | None = None,
    second_label: str | None = None,
) -> Any:
    first_series_label = first_label or _precision_recall_chart_label(
        first_chart,
        "Series 1",
    )
    second_series_label = second_label or _precision_recall_chart_label(
        second_chart,
        "Series 2",
    )

    combined_records = [
        {
            **record,
            "series_id": "series_1",
            "series_label": first_series_label,
        }
        for record in _extract_precision_recall_chart_records(first_chart)
    ]
    combined_records.extend(
        {
            **record,
            "series_id": "series_2",
            "series_label": second_series_label,
        }
        for record in _extract_precision_recall_chart_records(second_chart)
    )

    chart_definition = _load_chart_definition("precision_recall.json")
    chart_definition["data"]["values"] = combined_records
    chart_definition.pop("params", None)
    chart_definition["mark"]["fillOpacity"] = 0.08
    chart_definition["encoding"]["detail"] = {
        "field": "series_id",
        "type": "nominal",
    }
    chart_definition["encoding"]["color"] = {
        "field": "series_label",
        "type": "nominal",
        "title": "Curve",
        "scale": {
            "range": ["#4C78A8", "#F58518", "#54A24B", "#E45756"],
        },
        "legend": None,
    }
    chart_definition["encoding"]["tooltip"] = [
        {
            "field": "series_label",
            "type": "nominal",
            "title": "Curve",
        },
        *chart_definition["encoding"]["tooltip"],
    ]

    chart_mark = chart_definition.pop("mark")
    chart_encoding = chart_definition.pop("encoding")
    chart_definition["layer"] = [
        {
            "mark": chart_mark,
            "encoding": chart_encoding,
        },
        {
            "transform": [
                {
                    "window": [{"op": "rank", "as": "label_rank"}],
                    "sort": [
                        {"field": "recall", "order": "descending"},
                        {"field": "precision", "order": "descending"},
                    ],
                    "groupby": ["series_id"],
                },
                {"filter": "datum.label_rank === 1"},
            ],
            "mark": {
                "type": "text",
                "align": "left",
                "baseline": "middle",
                "dx": 6,
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
                    "scale": {
                        "range": ["#4C78A8", "#F58518", "#54A24B", "#E45756"],
                    },
                    "legend": None,
                },
                "detail": {
                    "field": "series_id",
                    "type": "nominal",
                },
            },
        },
    ]
    return render_chart_definition(chart_definition)


def build_threshold_selection_chart_definition(
    records: list[dict[str, Any]],
    add_metrics: list[str],
) -> dict[str, Any]:
    plot_records = _visual_chart_records(records)
    chart = _load_chart_definition("threshold_selection_tool.json")
    chart["data"]["values"] = plot_records

    metrics = ["precision", "recall", *add_metrics]
    chart["transform"][0]["fold"] = metrics
    return chart


def build_match_weight_rounding_expression(
    match_weight_round_to_nearest: float | None,
) -> str:
    if match_weight_round_to_nearest is None:
        return "m.match_weight"
    return (
        f"CAST({match_weight_round_to_nearest} AS DOUBLE) "
        f"* round(m.match_weight / {match_weight_round_to_nearest})"
    )


def compute_precision_recall_auc(
    con: duckdb.DuckDBPyConnection,
    threshold_metrics_sql: str,
) -> float | None:
    auc_row = con.sql(
        f"""
        WITH points AS (
            SELECT
                CAST(recall AS DOUBLE) AS recall,
                MAX(CAST(precision AS DOUBLE)) AS precision
            FROM ({threshold_metrics_sql})
            WHERE recall IS NOT NULL
              AND precision IS NOT NULL
            GROUP BY 1
        ),
        ordered AS (
            SELECT
                recall,
                precision,
                LAG(recall) OVER (ORDER BY recall) AS prev_recall,
                LAG(precision) OVER (ORDER BY recall) AS prev_precision
            FROM points
        ),
        auc_integral AS (
            SELECT
                SUM(
                    (recall - prev_recall)
                    * ((precision + prev_precision) / 2.0)
                ) AS auc
            FROM ordered
            WHERE prev_recall IS NOT NULL
        )
        SELECT
            CASE
                WHEN auc IS NULL THEN NULL
                ELSE LEAST(GREATEST(auc, 0.0), 1.0)
            END AS auc
        FROM auc_integral
        """
    ).fetchone()
    if auc_row is None or auc_row[0] is None:
        return None
    return float(auc_row[0])


def render_chart_definition(chart_definition: dict[str, Any]) -> Any:
    """Return an Altair chart when available, otherwise return raw Vega-Lite dict."""
    try:
        import altair as alt
    except ImportError:
        return chart_definition

    return alt.Chart.from_dict(chart_definition)
