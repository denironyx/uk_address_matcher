from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any

from benchmarking.comparisons.comparison_artifacts import (
    build_accuracy_comparison_rows,
    build_comparison_summary,
    build_stage_diagnostics_comparison_rows,
    write_comparison_chart_html,
)
from benchmarking.insights.types import PersistedBenchmarkRun

if TYPE_CHECKING:
    import duckdb


_RESULTS_ROOT = Path("benchmarking/results")
_HISTORY_FILE = "run_history.json"


def _safe_path_segment(value: str) -> str:
    lowered = value.strip().lower().replace(" ", "_")
    safe = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "_" for ch in lowered)
    return safe or "unknown_dataset"


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalise_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return _normalise_value(value.value)
    if isinstance(value, Decimal):
        return round(float(value), 10)
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value == float("inf"):
            return "Infinity"
        if value == float("-inf"):
            return "-Infinity"
        return round(value, 10)
    if isinstance(value, list):
        return [_normalise_value(v) for v in value]
    if isinstance(value, tuple):
        return [_normalise_value(v) for v in value]
    if isinstance(value, (set, frozenset)):
        normalised = [_normalise_value(v) for v in value]
        return sorted(normalised, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, dict):
        return {str(k): _normalise_value(v) for k, v in sorted(value.items())}

    # Fallback for complex runtime-only objects (e.g. Splink linker instances).
    return {"__type__": f"{value.__class__.__module__}.{value.__class__.__name__}"}


def _relation_to_records(relation: duckdb.DuckDBPyRelation) -> list[dict[str, Any]]:
    columns = relation.columns
    rows = relation.fetchall()
    records = [
        {column: _normalise_value(row[index]) for index, column in enumerate(columns)}
        for row in rows
    ]
    return sorted(records, key=lambda item: json.dumps(item, sort_keys=True))


def _normalise_hash_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return _normalise_hash_value(value.value)
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return str(value)
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value == float("inf"):
            return "Infinity"
        if value == float("-inf"):
            return "-Infinity"
        return repr(value)
    if isinstance(value, list):
        return [_normalise_hash_value(v) for v in value]
    if isinstance(value, tuple):
        return [_normalise_hash_value(v) for v in value]
    if isinstance(value, (set, frozenset)):
        normalised = [_normalise_hash_value(v) for v in value]
        return sorted(normalised, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, dict):
        return {str(k): _normalise_hash_value(v) for k, v in sorted(value.items())}

    return {"__type__": f"{value.__class__.__module__}.{value.__class__.__name__}"}


def _relation_to_hash_records(relation: duckdb.DuckDBPyRelation) -> list[dict[str, Any]]:
    columns = relation.columns
    rows = relation.fetchall()
    records = [
        {
            column: _normalise_hash_value(row[index])
            for index, column in enumerate(columns)
        }
        for row in rows
    ]
    return sorted(records, key=lambda item: json.dumps(item, sort_keys=True))


def _serialisable_stage(stage: Any) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if hasattr(stage, "__dict__"):
        for key, value in sorted(stage.__dict__.items()):
            if key.startswith("_"):
                continue
            if callable(value):
                continue
            params[key] = _normalise_value(value)

    return {
        "module": stage.__class__.__module__,
        "name": stage.__class__.__name__,
        "params": params,
    }


def _stage_fingerprint(stages: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    serialised = [_serialisable_stage(stage) for stage in stages]
    payload = json.dumps(serialised, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return digest, serialised


def _run_hash(
    *,
    dataset_key: str,
    accuracy_rows: list[dict[str, Any]],
) -> str:
    payload = {
        "dataset_key": dataset_key,
        "accuracy_table": accuracy_rows,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_history(path: Path) -> dict[str, Any]:
    history = _read_json(path)
    if not history:
        return {
            "version": 1,
            "runs_by_hash": {},
            "latest_by_group": {},
        }
    history.setdefault("runs_by_hash", {})
    history.setdefault("latest_by_group", {})
    return history


def _git_commit_hash() -> str | None:
    try:
        output = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if output.returncode != 0:
        return None
    commit = output.stdout.strip()
    return commit or None


def _to_relative(path: Path) -> str:
    return path.as_posix()


def _build_group_key(*, dataset_key: str, stage_fingerprint: str) -> str:
    return f"{dataset_key}:{stage_fingerprint}"


def persist_benchmark_run(
    *,
    dataset_key: str,
    dataset_label: str,
    stages: list[Any],
    accuracy_table: duckdb.DuckDBPyRelation,
    stage_diagnostics_table: duckdb.DuckDBPyRelation,
    timings: dict[str, float],
    total_rows: int,
    matched_rows: int,
    correct_matches: int,
    precision: float | None,
    recall: float | None,
    results_root: str = "benchmarking/results",
    enable_chart_exports: bool = True,
) -> PersistedBenchmarkRun:
    root = Path(results_root)
    history_path = root / _HISTORY_FILE

    created_at = _now_utc_iso()
    stage_fingerprint, stage_definition = _stage_fingerprint(stages)
    group_key = _build_group_key(
        dataset_key=dataset_key,
        stage_fingerprint=stage_fingerprint,
    )

    accuracy_rows = _relation_to_records(accuracy_table)
    accuracy_hash_rows = _relation_to_hash_records(accuracy_table)
    stage_rows = _relation_to_records(stage_diagnostics_table)
    run_hash = _run_hash(
        dataset_key=dataset_key,
        accuracy_rows=accuracy_hash_rows,
    )

    history = _load_history(history_path)
    runs_by_hash: dict[str, Any] = history["runs_by_hash"]
    latest_by_group: dict[str, str] = history["latest_by_group"]

    existing = runs_by_hash.get(run_hash)
    if existing is not None:
        latest_by_group[group_key] = run_hash
        history["latest_by_group"] = latest_by_group
        _atomic_write_json(history_path, history)
        return PersistedBenchmarkRun(
            run_hash=run_hash,
            group_key=group_key,
            created_at_utc=existing.get("created_at_utc", created_at),
            run_dir=existing["run_dir"],
            manifest_path=existing["manifest_path"],
            history_path=_to_relative(history_path),
            deduplicated=True,
            git_commit_hash=existing.get("git_commit_hash"),
            comparison=None,
        )

    date_bucket = created_at.split("T", 1)[0]
    dataset_segment = _safe_path_segment(dataset_key)
    run_dir = root / dataset_segment / date_bucket / run_hash
    charts_dir = run_dir / "charts"
    run_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    accuracy_path = run_dir / "accuracy_table.json"
    stage_path = run_dir / "stage_diagnostics.json"
    summary_path = run_dir / "comparison_summary.json"
    manifest_path = run_dir / "manifest.json"

    _atomic_write_json(accuracy_path, {"rows": accuracy_rows})
    _atomic_write_json(stage_path, {"rows": stage_rows})

    commit_hash = _git_commit_hash()

    baseline_hash = latest_by_group.get(group_key)
    comparison = None
    chart_paths: list[Path] = []
    if baseline_hash and baseline_hash in runs_by_hash:
        baseline_info = runs_by_hash[baseline_hash]
        baseline_accuracy = _read_json(
            _resolve_artifact_path(
                str(baseline_info["accuracy_table_path"]),
                results_root=root,
            )
        )
        baseline_stage = _read_json(
            _resolve_artifact_path(
                str(baseline_info["stage_diagnostics_path"]),
                results_root=root,
            )
        )

        accuracy_comparison_rows = build_accuracy_comparison_rows(
            baseline_rows=baseline_accuracy.get("rows", []),
            current_rows=accuracy_rows,
            baseline_hash=baseline_hash,
            current_hash=run_hash,
            baseline_git_commit_hash=baseline_info.get("git_commit_hash"),
            current_git_commit_hash=commit_hash,
        )
        stage_diagnostics_comparison_rows = build_stage_diagnostics_comparison_rows(
            baseline_rows=baseline_stage.get("rows", []),
            current_rows=stage_rows,
            baseline_hash=baseline_hash,
            current_hash=run_hash,
            baseline_git_commit_hash=baseline_info.get("git_commit_hash"),
            current_git_commit_hash=commit_hash,
        )
        accuracy_comparison_path = run_dir / "accuracy_comparison_table.json"
        stage_diagnostics_comparison_path = (
            run_dir / "stage_diagnostics_comparison_table.json"
        )
        _atomic_write_json(accuracy_comparison_path, accuracy_comparison_rows)
        _atomic_write_json(
            stage_diagnostics_comparison_path,
            stage_diagnostics_comparison_rows,
        )

        if enable_chart_exports:
            overall_chart = charts_dir / "overall_metrics.html"
            write_comparison_chart_html(
                path=overall_chart,
                title=f"Overall Metrics: {baseline_hash} vs {run_hash}",
                labels=["precision", "recall", "f1"],
                baseline_values=[
                    _normalise_metric_from_accuracy(
                        baseline_accuracy.get("rows", []),
                        "precision",
                    ),
                    _normalise_metric_from_accuracy(
                        baseline_accuracy.get("rows", []),
                        "recall",
                    ),
                    _normalise_metric_from_accuracy(
                        baseline_accuracy.get("rows", []),
                        "f1",
                    ),
                ],
                current_values=[
                    _normalise_metric_from_accuracy(accuracy_rows, "precision"),
                    _normalise_metric_from_accuracy(accuracy_rows, "recall"),
                    _normalise_metric_from_accuracy(accuracy_rows, "f1"),
                ],
            )
            chart_paths.append(overall_chart)

            stage_time_chart = charts_dir / "stage_elapsed_seconds.html"
            stage_names = [str(row.get("stage")) for row in stage_rows]
            write_comparison_chart_html(
                path=stage_time_chart,
                title=f"Stage Timing: {baseline_hash} vs {run_hash}",
                labels=stage_names,
                baseline_values=_stage_metric_values(
                    baseline_stage.get("rows", []),
                    stage_names,
                    "elapsed_seconds",
                ),
                current_values=_stage_metric_values(
                    stage_rows,
                    stage_names,
                    "elapsed_seconds",
                ),
            )
            chart_paths.append(stage_time_chart)

        comparison = build_comparison_summary(
            baseline_hash=baseline_hash,
            current_hash=run_hash,
            baseline_accuracy_rows=baseline_accuracy.get("rows", []),
            current_accuracy_rows=accuracy_rows,
            baseline_stage_rows=baseline_stage.get("rows", []),
            current_stage_rows=stage_rows,
            baseline_total_runtime_seconds=baseline_info.get("timings", {}).get(
                "total_runtime"
            ),
            current_total_runtime_seconds=timings.get("total_runtime"),
            summary_path=summary_path,
            chart_paths=chart_paths,
            accuracy_comparison_path=accuracy_comparison_path,
            stage_diagnostics_comparison_path=stage_diagnostics_comparison_path,
        )

    manifest = {
        "run_hash": run_hash,
        "dataset_key": dataset_key,
        "dataset_label": dataset_label,
        "created_at_utc": created_at,
        "group_key": group_key,
        "stage_fingerprint": stage_fingerprint,
        "stage_definition": stage_definition,
        "git_commit_hash": commit_hash,
        "timings": {k: round(float(v), 6) for k, v in timings.items()},
        "summary": {
            "total_rows": total_rows,
            "matched_rows": matched_rows,
            "correct_matches": correct_matches,
            "precision": precision,
            "recall": recall,
        },
        "artifacts": {
            "accuracy_table_path": _to_relative(accuracy_path),
            "stage_diagnostics_path": _to_relative(stage_path),
            "comparison_summary_path": _to_relative(summary_path)
            if comparison is not None
            else None,
            "accuracy_comparison_table_path": (
                comparison.accuracy_comparison_path if comparison is not None else None
            ),
            "stage_diagnostics_comparison_table_path": (
                comparison.stage_diagnostics_comparison_path
                if comparison is not None
                else None
            ),
            "chart_paths": [_to_relative(path) for path in chart_paths],
        },
    }
    _atomic_write_json(manifest_path, manifest)

    runs_by_hash[run_hash] = {
        "run_hash": run_hash,
        "dataset_key": dataset_key,
        "dataset_label": dataset_label,
        "created_at_utc": created_at,
        "group_key": group_key,
        "stage_fingerprint": stage_fingerprint,
        "run_dir": _to_relative(run_dir),
        "manifest_path": _to_relative(manifest_path),
        "accuracy_table_path": _to_relative(accuracy_path),
        "stage_diagnostics_path": _to_relative(stage_path),
        "timings": {k: round(float(v), 6) for k, v in timings.items()},
        "git_commit_hash": commit_hash,
    }
    latest_by_group[group_key] = run_hash

    history["runs_by_hash"] = runs_by_hash
    history["latest_by_group"] = latest_by_group
    _atomic_write_json(history_path, history)

    return PersistedBenchmarkRun(
        run_hash=run_hash,
        group_key=group_key,
        created_at_utc=created_at,
        run_dir=_to_relative(run_dir),
        manifest_path=_to_relative(manifest_path),
        history_path=_to_relative(history_path),
        deduplicated=False,
        git_commit_hash=commit_hash,
        comparison=comparison,
    )


def _normalise_metric_from_accuracy(
    rows: list[dict[str, Any]],
    metric_name: str,
) -> float | None:
    for row in rows:
        if row.get("stage") == "overall":
            value = row.get(metric_name)
            return None if value is None else float(value)
    return None


def _stage_metric_values(
    rows: list[dict[str, Any]],
    stage_names: list[str],
    metric_name: str,
) -> list[float | None]:
    indexed = {str(row.get("stage")): row for row in rows}
    values: list[float | None] = []
    for stage_name in stage_names:
        value = indexed.get(stage_name, {}).get(metric_name)
        values.append(None if value is None else float(value))
    return values


def _resolve_artifact_path(path_value: str, *, results_root: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return results_root / path


def _comparison_artifact_paths(
    *,
    current_run_dir: Path,
    baseline_hash: str,
    current_hash: str,
    export_charts: bool,
) -> tuple[Path, Path, Path]:
    charts_dir = current_run_dir / "charts"
    if export_charts:
        charts_dir.mkdir(parents=True, exist_ok=True)

    summary_path = (
        current_run_dir / f"comparison_summary_{baseline_hash}_vs_{current_hash}.json"
    )
    overall_chart = charts_dir / f"overall_metrics_{baseline_hash}_vs_{current_hash}.html"
    stage_chart = (
        charts_dir / f"stage_elapsed_seconds_{baseline_hash}_vs_{current_hash}.html"
    )
    return summary_path, overall_chart, stage_chart


def compare_persisted_runs(
    *,
    results_root: str = "benchmarking/results",
    comparison_hash: str,
    baseline_hash: str,
    export_charts: bool = True,
) -> PersistedBenchmarkRun:
    """Compare two explicit persisted runs by hash.

    ``baseline_hash`` provides baseline values, and ``comparison_hash`` is compared
    against it.
    """
    root = Path(results_root)
    history_path = root / _HISTORY_FILE
    history = _load_history(history_path)
    runs_by_hash: dict[str, Any] = history.get("runs_by_hash", {})

    if not runs_by_hash:
        raise ValueError(f"No persisted benchmark runs found under '{results_root}'.")

    if comparison_hash not in runs_by_hash:
        raise ValueError(
            f"Unknown comparison_hash '{comparison_hash}'. "
            "Check benchmarking/results/run_history.json for available hashes."
        )
    if baseline_hash not in runs_by_hash:
        raise ValueError(
            f"Unknown baseline_hash '{baseline_hash}'. "
            "Check benchmarking/results/run_history.json for available hashes."
        )

    current_info = runs_by_hash[comparison_hash]
    baseline_info = runs_by_hash[baseline_hash]

    current_accuracy = _read_json(
        _resolve_artifact_path(
            str(current_info["accuracy_table_path"]),
            results_root=root,
        )
    )
    current_stage = _read_json(
        _resolve_artifact_path(
            str(current_info["stage_diagnostics_path"]),
            results_root=root,
        )
    )
    baseline_accuracy = _read_json(
        _resolve_artifact_path(
            str(baseline_info["accuracy_table_path"]),
            results_root=root,
        )
    )
    baseline_stage = _read_json(
        _resolve_artifact_path(
            str(baseline_info["stage_diagnostics_path"]),
            results_root=root,
        )
    )

    current_run_dir = _resolve_artifact_path(
        str(current_info["run_dir"]), results_root=root
    )
    summary_path, overall_chart, stage_chart = _comparison_artifact_paths(
        current_run_dir=current_run_dir,
        baseline_hash=baseline_hash,
        current_hash=comparison_hash,
        export_charts=export_charts,
    )
    accuracy_comparison_path = (
        current_run_dir
        / f"accuracy_comparison_table_{baseline_hash}_vs_{comparison_hash}.json"
    )
    stage_diagnostics_comparison_path = (
        current_run_dir
        / f"stage_diagnostics_comparison_table_{baseline_hash}_vs_{comparison_hash}.json"
    )

    accuracy_comparison_rows = build_accuracy_comparison_rows(
        baseline_rows=baseline_accuracy.get("rows", []),
        current_rows=current_accuracy.get("rows", []),
        baseline_hash=baseline_hash,
        current_hash=comparison_hash,
        baseline_git_commit_hash=baseline_info.get("git_commit_hash"),
        current_git_commit_hash=current_info.get("git_commit_hash"),
    )
    stage_diagnostics_comparison_rows = build_stage_diagnostics_comparison_rows(
        baseline_rows=baseline_stage.get("rows", []),
        current_rows=current_stage.get("rows", []),
        baseline_hash=baseline_hash,
        current_hash=comparison_hash,
        baseline_git_commit_hash=baseline_info.get("git_commit_hash"),
        current_git_commit_hash=current_info.get("git_commit_hash"),
    )
    _atomic_write_json(accuracy_comparison_path, accuracy_comparison_rows)
    _atomic_write_json(
        stage_diagnostics_comparison_path,
        stage_diagnostics_comparison_rows,
    )

    chart_paths: list[Path] = []
    if export_charts:
        write_comparison_chart_html(
            path=overall_chart,
            title=(f"Overall Metrics: {baseline_hash} vs {comparison_hash}"),
            labels=["precision", "recall", "f1"],
            baseline_values=[
                _normalise_metric_from_accuracy(
                    baseline_accuracy.get("rows", []),
                    "precision",
                ),
                _normalise_metric_from_accuracy(
                    baseline_accuracy.get("rows", []),
                    "recall",
                ),
                _normalise_metric_from_accuracy(
                    baseline_accuracy.get("rows", []),
                    "f1",
                ),
            ],
            current_values=[
                _normalise_metric_from_accuracy(
                    current_accuracy.get("rows", []),
                    "precision",
                ),
                _normalise_metric_from_accuracy(
                    current_accuracy.get("rows", []),
                    "recall",
                ),
                _normalise_metric_from_accuracy(current_accuracy.get("rows", []), "f1"),
            ],
        )
        chart_paths.append(overall_chart)

        stage_names = [str(row.get("stage")) for row in current_stage.get("rows", [])]
        write_comparison_chart_html(
            path=stage_chart,
            title=(f"Stage Timing: {baseline_hash} vs {comparison_hash}"),
            labels=stage_names,
            baseline_values=_stage_metric_values(
                baseline_stage.get("rows", []),
                stage_names,
                "elapsed_seconds",
            ),
            current_values=_stage_metric_values(
                current_stage.get("rows", []),
                stage_names,
                "elapsed_seconds",
            ),
        )
        chart_paths.append(stage_chart)

    comparison = build_comparison_summary(
        baseline_hash=baseline_hash,
        current_hash=comparison_hash,
        baseline_accuracy_rows=baseline_accuracy.get("rows", []),
        current_accuracy_rows=current_accuracy.get("rows", []),
        baseline_stage_rows=baseline_stage.get("rows", []),
        current_stage_rows=current_stage.get("rows", []),
        baseline_total_runtime_seconds=baseline_info.get("timings", {}).get(
            "total_runtime"
        ),
        current_total_runtime_seconds=current_info.get("timings", {}).get(
            "total_runtime"
        ),
        summary_path=summary_path,
        chart_paths=chart_paths,
        accuracy_comparison_path=accuracy_comparison_path,
        stage_diagnostics_comparison_path=stage_diagnostics_comparison_path,
    )

    return PersistedBenchmarkRun(
        run_hash=comparison_hash,
        group_key=str(current_info.get("group_key", "")),
        created_at_utc=str(current_info.get("created_at_utc", "")),
        run_dir=str(current_info.get("run_dir", "")),
        manifest_path=str(current_info.get("manifest_path", "")),
        history_path=_to_relative(history_path),
        deduplicated=False,
        git_commit_hash=current_info.get("git_commit_hash"),
        comparison=comparison,
    )
