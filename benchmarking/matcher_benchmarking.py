import os
from pathlib import Path
from time import perf_counter
from typing import Optional

from benchmarking.analysis import (
    print_stages_benchmark_header,
    print_unmatched_samples,
)
from benchmarking.analysis.accuracy import calculate_accuracy_metrics
from benchmarking.analysis.mismatches import (
    analyse_mismatches,
    print_mismatch_analysis,
)
from benchmarking.datasets import get_dataset_info, load_benchmark_data
from benchmarking.utils.io import apply_env_from_private_config, setup_connection
from benchmarking.utils.timing import format_timing_summary, time_phase
from uk_address_matcher import (
    AddressMatcher,
    ExactMatchStage,
)
from uk_address_matcher.linking_model.matching.stages.splink import SplinkStage
from uk_address_matcher.sql_pipeline.runner import DebugOptions

# ============================================================================
# Configuration
# ============================================================================

# DATASET_NAME = "lambeth_council"
DATASET_NAME = "hackney_council"
apply_env_from_private_config()

OS_DATA_PATH: Path | None = None
CANONICAL_PREPARED_FOLDER: Path | None = (
    Path(os.getenv("UKAM_OS_CANONICAL_PREPARED"))
    if os.getenv("UKAM_OS_CANONICAL_PREPARED")
    else None
)
# DEBUG_OPTIONS: Optional[DebugOptions] = DebugOptions(
#     pretty_print_sql=True,
#     debug_incremental=True,
#     debug_mode=True,
#     debug_show_sql=True,
# )
DEBUG_OPTIONS: Optional[DebugOptions] = None
SAMPLE_MODE = False
# If you need to run in low-memory environments, set this to True to
# filter the canonical dataset to only include postcodes present in the
# messy dataset. You won't get a full benchmark, but it can be useful
# for testing and debugging.
FILTER_CANONICAL_BY_MESSY_POSTCODES = True

# Stage configuration
STAGES = [
    ExactMatchStage(),
    # UniqueTrigramStage(),
    SplinkStage(
        predict_threshold_match_weight=10,
        improve_threshold_match_weight=-20,
        final_match_weight_threshold=10,
        final_distinguishability_threshold=5,
        include_full_postcode_block=False,
        retain_intermediate_calculation_columns=False,
    ),
]

# Data cleaning configuration
# If True, load raw canonical data and clean it on the fly (derives inverted index)
# If False, load pre-cleaned canonical data (faster, but won't have exploding_unique_ids)
CLEAN_CANONICAL_ON_THE_FLY = False
# If True, derive term frequencies from canonical data on the fly
# If False, use pre-baked term frequencies
# (only relevant when CLEAN_CANONICAL_ON_THE_FLY=True)
DERIVE_TERM_FREQUENCIES_ON_THE_FLY = False

# Analysis configuration
MISMATCH_SAMPLES_PER_REASON = 10  # Random samples per match_reason
TOP_WORST_MISMATCHES = 10  # Worst mismatches by similarity
UNMATCHED_SAMPLES = 10  # Sample unresolved records to inspect

# ============================================================================
# Setup
# ============================================================================

print("Initialising benchmark environment...")
variant_label = "configured_stages"
variant_timings: dict[str, dict[str, float]] = {}


def timed_phase(phase_name: str, func):
    t0 = perf_counter()
    result = func()
    elapsed = perf_counter() - t0
    variant_timings.setdefault(variant_label, {})[phase_name] = elapsed
    print(f"  {phase_name}: {elapsed:.2f}s")
    return result


con = setup_connection()
df_messy_clean, df_os_clean = timed_phase(
    "load_benchmark_data",
    lambda: load_benchmark_data(
        con,
        DATASET_NAME,
        canonical_prepared_folder=CANONICAL_PREPARED_FOLDER,
        os_data_path=OS_DATA_PATH,
        include_term_frequencies=True,
        sample_mode=SAMPLE_MODE,
        filter_canonical_by_messy_postcodes=FILTER_CANONICAL_BY_MESSY_POSTCODES,
        clean_canonical_on_the_fly=CLEAN_CANONICAL_ON_THE_FLY,
        derive_term_frequencies_on_the_fly=DERIVE_TERM_FREQUENCIES_ON_THE_FLY,
    ),
)
con.sql("DROP TABLE IF EXISTS df_messy")
df_messy_clean.to_table("df_messy_clean")
dataset_info = get_dataset_info(DATASET_NAME)

print_stages_benchmark_header(
    dataset_name=dataset_info.name,
    variant_name=variant_label,
    stages=STAGES,
)

df_messy_for_matching = con.sql(
    "SELECT * EXCLUDE (dataset_name) FROM df_messy_clean"
).execute()

with time_phase(variant_timings, variant_label, "pipeline"):
    matcher = timed_phase(
        "address_matcher_init",
        lambda: AddressMatcher(
            canonical_addresses=df_os_clean,
            addresses_to_match=df_messy_for_matching,
            con=con,
            stages=STAGES,
            debug_options=DEBUG_OPTIONS,
        ),
    )

    match_result = timed_phase("matcher_match", matcher.match)
    match_candidates = timed_phase(
        "materialise_match_results", lambda: match_result.matches()
    )

pipeline_duration = variant_timings[variant_label]["pipeline"]
print(f"⏱  Pipeline completed in {pipeline_duration:.2f} seconds.\n")

# Bring `dataset_name` back for analysis
match_candidates = timed_phase(
    "join_dataset_name_back",
    lambda: match_candidates.join(
        timed_phase(
            "create_dataset_name_lookup",
            lambda: df_messy_clean.select("ukam_address_id, dataset_name"),
        ),
        condition="ukam_address_id",
        how="left",
    ),
)
con.sql("DROP TABLE IF EXISTS benchmark_match_candidates")
match_candidates.to_table("benchmark_match_candidates")
print("--- Match Reason Breakdown ---\n")
timed_phase("print_match_metrics", lambda: print(match_result.match_metrics()))

print("\n--- Accuracy Metrics ---\n")
accuracy = timed_phase(
    "calculate_accuracy_metrics",
    lambda: calculate_accuracy_metrics(match_candidates),
)
timed_phase("show_accuracy_metrics", lambda: accuracy.show(max_width=10000))
print_unmatched_samples(
    con,
    "benchmark_match_candidates",
    sample_size=UNMATCHED_SAMPLES,
)

incorrect_count = timed_phase(
    "count_incorrect_matches",
    lambda: (
        match_candidates.filter(
            "match_reason IS NOT NULL AND ukam_label != resolved_canonical_id"
        )
        .count("*")
        .fetchone()[0]
    ),
)

if incorrect_count > 0:
    print(f"\n📊 Found {incorrect_count:,} incorrect matches. Analysing mismatches...\n")
    mismatch_results = timed_phase(
        "analyse_mismatches",
        lambda: analyse_mismatches(
            ukam_matches=match_candidates,
            ukam_canonical=df_os_clean,
            ukam_messy=df_messy_clean,
            samples_per_reason=MISMATCH_SAMPLES_PER_REASON,
            top_worst=TOP_WORST_MISMATCHES,
        ),
    )
    timed_phase(
        "print_mismatch_analysis", lambda: print_mismatch_analysis(mismatch_results)
    )
else:
    print("\n✓ No incorrect matches found!\n")

print("\nTiming summary:")
for line in format_timing_summary(variant_timings):
    print(line)
