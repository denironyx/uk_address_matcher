# Benchmark Experiment Artefacts

Persisted benchmark runs live under:

```text
benchmarking/results/<dataset>/<yyyy-mm-dd>/<run_id>/
```

## Files To Read First

- `manifest.json`
  - Run metadata, stage definition, summary, timings, and chart paths.

- `accuracy_table.json`
  - Precision, recall, F1, and stage outcome counts.

- `stage_diagnostics.json`
  - Rows entering each stage, matched counts, and timing detail.

- `comparison_summary_<baseline>_vs_<current>.json`
  - Machine-readable deltas for comparison runs.

- `comparison_report_<baseline>_vs_<current>.md`
  - Human-readable comparison summary.

- `charts/precision_recall_overlay_<baseline>_vs_<current>.html`
  - Primary comparison chart.

- `charts/precision_recall_overlay_<baseline>_vs_<current>.vl.json`
  - Vega-Lite spec for the same overlay chart.

## When To Read Which Artefact

- Start with `manifest.json` if you need run IDs, stage settings, summary counts, or output paths.
- Read `comparison_report_*.md` first when the user wants a human-readable summary.
- Read `comparison_summary_*.json` first when you need exact deltas or want to quote numbers programmatically.
- Read the overlay chart or spec when the user asks whether the change is broadly better or worse across thresholds.
- Read `stage_diagnostics.json` when the question is about runtime or stage-level movement.

## Run Comparison Rules

- `run_id` is the user-facing identifier.
- Comparisons are dataset-specific.
- `COMPARISON_BASELINE_RUN_ID = "latest"` is the default comparison mode in normal reruns.
- Persisted artefacts are preferred over notebook output or raw terminal logs.