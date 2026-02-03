from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from benchmarking.datasets.hackney_council import (
    HACKNEY_COUNCIL_INFO,
    get_hackney_council_data,
)
from benchmarking.datasets.lambeth_council import (
    LAMBETH_COUNCIL_INFO,
    get_lambeth_council_data,
)
from benchmarking.datasets.registry import (
    DatasetInfo,
    _DATASET_REGISTRY,
    get_all_dataset_info,
    get_dataset_info,
    list_datasets,
    load_dataset,
    register_dataset,
)
from benchmarking.datasets.sources import (
    CanonicalConfig,
    SourceConfig,
    load_canonical_data,
)
from uk_address_matcher import (
    clean_data_pre_term_frequencies,
    derive_inverted_index,
    derive_term_frequencies_table,
    prepare_data_for_matching,
)

if TYPE_CHECKING:
    import duckdb

# Register available datasets
register_dataset("lambeth_council", LAMBETH_COUNCIL_INFO, get_lambeth_council_data)
register_dataset("hackney_council", HACKNEY_COUNCIL_INFO, get_hackney_council_data)


def load_benchmark_data(
    con: duckdb.DuckDBPyConnection,
    dataset_name: str,
    os_data_path: Path | None = None,
    include_term_frequencies: bool = False,
    sample_mode: bool = False,
    clean_canonical_on_the_fly: bool = False,
    derive_term_frequencies_on_the_fly: bool = True,
) -> tuple[duckdb.DuckDBPyRelation, duckdb.DuckDBPyRelation]:
    """Load a benchmark dataset with messy and canonical data.

    The canonical OS data is loaded once and can be reused across multiple
    benchmark datasets for efficiency.

    Parameters
    ----------
    con:
        Active DuckDB connection.
    dataset_name:
        Name of the registered dataset to load.
    os_data_path:
        Optional path to canonical OS data. If None, uses default location.
    include_term_frequencies:
        Whether to include term frequency information in the output.
    sample_mode:
        If True, load 100k canonical records and 10k messy records (deterministically).
        If False, load all records.
    clean_canonical_on_the_fly:
        If True, load raw canonical data and clean it on the fly using
        prepare_data_for_matching. This also derives the inverted index from
        canonical data and uses it when cleaning messy data.
        If False, load pre-cleaned canonical data (default).
    derive_term_frequencies_on_the_fly:
        If True (and clean_canonical_on_the_fly is True), derive term frequencies
        from canonical data. If False, use pre-baked term frequencies.
        Only relevant when clean_canonical_on_the_fly is True.

    Returns
    -------
    tuple[duckdb.DuckDBPyRelation, duckdb.DuckDBPyRelation]
        Messy input data and canonical OS data.
    """
    print(f"Available datasets: {', '.join(list_datasets())}")
    print(f"Loading dataset: {dataset_name}\n")

    # Load raw messy data with optional sampling
    df_messy_raw = load_dataset(dataset_name, con, sample_mode=sample_mode)

    # Load canonical data once with optional sampling
    canonical_config = (
        CanonicalConfig(local_path=os_data_path)
        if os_data_path
        else CanonicalConfig.default(use_raw=clean_canonical_on_the_fly)
    )
    df_canonical_loaded = load_canonical_data(
        con, canonical_config, sample_mode=sample_mode
    )

    # Apply dataset-specific canonical filter if defined
    canonical_filter_sql = _DATASET_REGISTRY[dataset_name].info.canonical_filter_sql
    if canonical_filter_sql is not None and canonical_filter_sql.strip():
        df_canonical_loaded = con.sql(
            f"""
            SELECT *
            FROM df_canonical_loaded
            WHERE {canonical_filter_sql.strip()}
            """
        )

    if clean_canonical_on_the_fly:
        # Clean canonical data on the fly
        print("Cleaning canonical data on the fly...")

        # Optionally derive term frequencies from canonical data
        tf_table = None
        if derive_term_frequencies_on_the_fly:
            print("Deriving term frequencies from canonical data...")
            tf_table = derive_term_frequencies_table(df_canonical_loaded, con=con)

        # Derive inverted index from canonical data
        print("Deriving inverted index from canonical data...")
        inverted_index = derive_inverted_index(
            df_canonical_loaded,
            con=con,
            num_of_chunks=5,
        )

        # Clean canonical data (no inverted index needed for canonical)
        print("Preparing canonical data for matching...")
        df_canonical = prepare_data_for_matching(
            df_canonical_loaded,
            con=con,
            term_frequency_lookup=tf_table,
        )

        # Clean messy data with inverted index from canonical
        print("Preparing messy data for matching...")
        if include_term_frequencies:
            df_messy = prepare_data_for_matching(
                df_messy_raw,
                con=con,
                term_frequency_lookup=tf_table,
                inverted_index=inverted_index,
            )
        else:
            df_messy = clean_data_pre_term_frequencies(df_messy_raw, con)
    else:
        # Use pre-cleaned canonical data (original behavior)
        df_canonical = df_canonical_loaded

        # Apply cleaning logic to messy data
        if include_term_frequencies:
            df_messy = prepare_data_for_matching(df_messy_raw, con)
        else:
            df_messy = clean_data_pre_term_frequencies(df_messy_raw, con)

    # Show dataset info
    info = get_dataset_info(dataset_name)
    record_count = df_messy.count("*").fetchone()[0]
    print(info.summary(record_count))
    print()

    return df_messy, df_canonical


__all__ = [
    "DatasetInfo",
    "CanonicalConfig",
    "SourceConfig",
    "get_dataset_info",
    "get_all_dataset_info",
    "list_datasets",
    "load_benchmark_data",
    "load_canonical_data",
    "load_dataset",
    "register_dataset",
    "LAMBETH_COUNCIL_INFO",
    "get_lambeth_council_data",
    "HACKNEY_COUNCIL_INFO",
    "get_hackney_council_data",
]
