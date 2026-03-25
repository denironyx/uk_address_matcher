from __future__ import annotations

import json
from importlib.resources import files
from os import PathLike
from pathlib import Path
from typing import Any

from uk_address_matcher.analysis.accuracy_analysis import render_chart_definition

_OVERLAY_COLOUR_RANGE = ["#4C78A8", "#F58518", "#54A24B", "#E45756"]


def _load_precision_recall_chart_definition() -> dict[str, Any]:
    chart_path = files("uk_address_matcher.analysis.chart_defs").joinpath(
        "precision_recall.json"
    )
    with chart_path.open("r", encoding="utf-8") as f:
        return json.load(f)


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

    chart_definition = _load_precision_recall_chart_definition()
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
            "range": _OVERLAY_COLOUR_RANGE,
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
                        "range": _OVERLAY_COLOUR_RANGE,
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
