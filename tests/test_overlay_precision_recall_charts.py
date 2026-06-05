from __future__ import annotations

from uk_address_matcher.analysis.overlay_precision_recall_charts import (
    _LABEL_MIN_VERTICAL_GAP,
    _OVERLAY_COLOUR_RANGE,
    _apply_label_offsets,
    _build_overlay_chart_definition,
)


def test_apply_label_offsets_separates_close_endpoint_labels() -> None:
    adjusted = _apply_label_offsets(
        [
            {
                "series_label": "Hackney 320bdce991462589",
                "recall": 0.962,
                "precision": 0.976,
                "is_baseline": True,
            },
            {
                "series_label": "Hackney 366b7bec7391f5df",
                "recall": 0.958,
                "precision": 0.974,
                "is_baseline": False,
            },
            {
                "series_label": "Hackney 739f3335b49a58f0",
                "recall": 0.812,
                "precision": 0.913,
                "is_baseline": False,
            },
        ]
    )

    adjusted_by_label = {record["series_label"]: record for record in adjusted}
    left = adjusted_by_label["Hackney 320bdce991462589"]
    right = adjusted_by_label["Hackney 366b7bec7391f5df"]

    assert (
        abs(float(left["label_precision"]) - float(right["label_precision"]))
        >= _LABEL_MIN_VERTICAL_GAP
    )
    assert left["label_has_connector"] or right["label_has_connector"]


def test_overlay_chart_definition_includes_hover_guides_and_solid_labels() -> None:
    chart_definition = _build_overlay_chart_definition(
        curve_records=[
            {
                "series_id": "baseline",
                "series_label": "Baseline",
                "is_baseline": True,
                "recall": 0.91,
                "precision": 0.96,
            },
            {
                "series_id": "comparison_1",
                "series_label": "Comparison",
                "is_baseline": False,
                "recall": 0.89,
                "precision": 0.955,
            },
        ],
        diff_records=[],
        label_records=[
            {
                "series_label": "Baseline",
                "is_baseline": True,
                "recall": 0.91,
                "precision": 0.96,
            },
            {
                "series_label": "Comparison",
                "is_baseline": False,
                "recall": 0.89,
                "precision": 0.955,
            },
        ],
    )

    top_panel = chart_definition["vconcat"][0]
    assert "params" not in chart_definition
    assert "params" not in top_panel

    hover_source_layer = next(
        layer for layer in top_panel["layer"] if layer.get("params")
    )
    assert hover_source_layer["params"][0]["name"] == "curve_hover"

    hover_rule_layers = [
        layer
        for layer in top_panel["layer"]
        if layer.get("mark", {}).get("type") == "rule"
        and layer.get("transform")
        == [{"filter": {"param": "curve_hover", "empty": False}}]
    ]
    assert len(hover_rule_layers) == 2

    label_layer = next(
        layer
        for layer in top_panel["layer"]
        if layer.get("mark", {}).get("type") == "text"
    )
    assert "stroke" not in label_layer["mark"]
    assert label_layer["encoding"]["y"]["field"] == "label_precision"

    connector_layer = next(
        layer
        for layer in top_panel["layer"]
        if layer.get("mark", {}).get("type") == "rule"
        and layer.get("encoding", {}).get("y2", {}).get("field") == "label_precision"
    )
    assert connector_layer["transform"] == [{"filter": "datum.label_has_connector"}]

    top_colour_scale = top_panel["layer"][0]["encoding"]["color"]["scale"]
    assert top_colour_scale["domain"] == ["Baseline", "Comparison"]
    assert top_colour_scale["range"] == _OVERLAY_COLOUR_RANGE[:2]

    bottom_colour_scale = chart_definition["vconcat"][1]["layer"][1]["encoding"]["color"][
        "scale"
    ]
    assert bottom_colour_scale["domain"] == ["Comparison"]
    assert bottom_colour_scale["range"] == [_OVERLAY_COLOUR_RANGE[1]]
