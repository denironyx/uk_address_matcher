from __future__ import annotations

from benchmarking.config.datasets import (
    get_dataset_definition,
    list_dataset_keys,
)
from benchmarking.insights.reporting import (
    print_benchmark_summary,
    print_diagnostics,
)
from benchmarking.insights.types import BenchmarkOutputOptions
from benchmarking.runner import run_selected_datasets
from benchmarking.settings import (
    CANONICAL_FILTER_SQL,
    CANONICAL_PATH,
    SAMPLE_MODE,
)
from uk_address_matcher import (
    ExactMatchStage,
    NgramJaccardStage,
    PeeledAddressStage,
)

SELECTED_DATASETS: str | list[str] = "all"
SELECTED_DATASETS: str | list[str] = "hackney"
STAGES = [
    ExactMatchStage(),
    NgramJaccardStage(min_similarity=0.9),
    PeeledAddressStage(),
    # SplinkStage(),
]
APPLY_CANONICAL_FILTER = True

# Defaults: always print summary sections (match breakdown, run totals, timings),
# with selected diagnostics enabled and successful/unmatched diagnostics opt-in.
OUTPUT_OPTIONS = BenchmarkOutputOptions()

print(f"Applying canonical filter: {APPLY_CANONICAL_FILTER}")


def print_available_datasets() -> None:
    print("Available datasets:")
    for key in list_dataset_keys():
        definition = get_dataset_definition(key)
        print(f"- {key}: {definition['label']} ({definition['s3_key']})")

    print()


print_available_datasets()

results = run_selected_datasets(
    selected_datasets=SELECTED_DATASETS,
    canonical_path=CANONICAL_PATH,
    stages=STAGES,
    sample_mode=SAMPLE_MODE,
    canonical_address_filter=(CANONICAL_FILTER_SQL if APPLY_CANONICAL_FILTER else None),
    enable_diagnostics=OUTPUT_OPTIONS.enable_diagnostics(),
)
print_benchmark_summary(results, output_options=OUTPUT_OPTIONS)

if OUTPUT_OPTIONS.enable_diagnostics():
    print_diagnostics(results, output_options=OUTPUT_OPTIONS)
