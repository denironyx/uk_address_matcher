from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb


def print_benchmark(dataset_name: str, variant_name: str) -> None:
    """Print a clear header for benchmark run.

    Parameters
    ----------
    dataset_name:
        Name of the dataset being benchmarked.
    variant_name:
        Name of the pipeline variant being run.
    enabled_stages:
        List of enabled stages, or None if only default stages.
    """
    print("\n" + "=" * 80)
    print(f"BENCHMARK RUN: {variant_name}")
    print("=" * 80)
    print(f"Dataset: {dataset_name}")


def _format_stage_name(stage: object) -> str:
    if hasattr(stage, "__class__"):
        return stage.__class__.__name__
    return str(stage)


def print_stages_benchmark_header(
    dataset_name: str, variant_name: str, stages: list | None = None
) -> None:
    """Print a clear header for benchmark run.

    Parameters
    ----------
    dataset_name:
        Name of the dataset being benchmarked.
    variant_name:
        Name of the pipeline variant being run.
    stages:
        List of stages executed for this variant, or None if not specified.
    """
    print_benchmark(dataset_name, variant_name)

    if stages is None:
        print("Stages: default stages")
    else:
        stage_names = [_format_stage_name(stage) for stage in stages]
        print(f"Stages: {', '.join(stage_names)}")

    print("=" * 80 + "\n")


def print_unmatched_samples(
    con: duckdb.DuckDBPyConnection,
    match_table: str,
    *,
    sample_size: int = 10,
) -> None:
    """Print unmatched record count and sample rows from a match results table."""
    unmatched_count = con.sql(
        f"""
        SELECT COUNT(*) AS unmatched_count
        FROM {match_table}
        WHERE match_reason IS NULL
        """
    ).fetchone()[0]

    print("\n--- Unmatched Records ---\n")
    print(f"Total unmatched records: {unmatched_count:,}")

    if unmatched_count == 0:
        print("✓ No unmatched records found.")
        return

    available_columns = set(con.sql(f"SELECT * FROM {match_table} LIMIT 0").columns)
    preferred_columns = [
        "dataset_name",
        "unique_id",
        "original_address_concat",
        "postcode",
        "ukam_label",
    ]
    selected_columns = [col for col in preferred_columns if col in available_columns]

    if selected_columns:
        projection = ", ".join(selected_columns)
    else:
        projection = "*"

    con.sql(
        f"""
        SELECT {projection}
        FROM {match_table}
        WHERE match_reason IS NULL
        LIMIT {sample_size}
        """
    ).show(max_width=10000)
