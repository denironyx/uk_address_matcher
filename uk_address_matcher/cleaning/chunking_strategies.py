from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional

from duckdb import DuckDBPyConnection, DuckDBPyRelation

from uk_address_matcher.cleaning.pipelines import (
    QUEUE_FOR_TF_DERIVATION,
    _clean_data_using_precomputed_rel_tok_freq,
    _clean_data_pre_term_frequencies,
    _create_term_frequency_tables,
    _ensure_postcode_column,
)
from uk_address_matcher.sql_pipeline.runner import create_sql_pipeline
from uk_address_matcher.sql_pipeline.helpers import _uid

if TYPE_CHECKING:
    from uk_address_matcher.sql_pipeline.runner import DebugOptions

logger = logging.getLogger("uk_address_matcher")


def _format_elapsed(elapsed_seconds: float) -> str:
    total_seconds = int(round(max(0.0, elapsed_seconds)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds:02d}s"


def _log_progress(
    total_records: int,
    processed_records: int,
    stage_type: str,
    *,
    chunk_index: int | None = None,
    total_chunks: int | None = None,
    chunk_elapsed_seconds: float | None = None,
) -> None:
    percentage_complete = (
        processed_records / total_records if total_records > 0 else 1.0
    )

    message = (
        f"{stage_type}"
        f"{processed_records:,.0f} records ({percentage_complete:.0%} complete)"
    )
    if chunk_elapsed_seconds is not None:
        chunk_suffix = ""
        if chunk_index is not None and total_chunks is not None:
            chunk_suffix = f"chunk {chunk_index + 1}/{total_chunks} "
        message += f" - {chunk_suffix}took {_format_elapsed(chunk_elapsed_seconds)}"

    logger.info(message)


def _calculate_chunk_size(total_records: int, num_of_chunks: int) -> int:
    if total_records <= 0:
        raise ValueError(
            "Supplied address table has no records. Please provide a non-empty table."
        )

    # Ensure chunk size is reasonable: minimum 10k records per chunk
    max_chunks = max(1, total_records // 10_000)
    num_of_chunks = max(1, min(num_of_chunks, max_chunks))
    chunk_size = (total_records + num_of_chunks - 1) // num_of_chunks
    return max(1, chunk_size)


def clean_data_pre_term_frequencies(
    address_table: DuckDBPyRelation,
    con: DuckDBPyConnection,
    num_of_chunks: int = 10,
    *,
    debug_options: Optional[DebugOptions] = None,
) -> DuckDBPyRelation:
    """Clean address data with foundational steps only (no term frequencies).

    Applies the minimal set of preprocessing transformations: trimming, upper-casing,
    parsing numeric and flat position information, and tokenisation. This is useful
    when you need lightweight cleaning without term frequency analysis.

    Args:
        address_table: Input address relation with standard schema.
        con: DuckDB connection.
        num_of_chunks: Number of chunks to split the data into. Data is processed
            in batches and results are unioned. Set to 1 for no chunking.
        debug_options: Optional debug configuration for pipeline execution.
            Note: Debug options are only applied on the first iteration to avoid
            excessive logging output.

    Returns:
        Cleaned address data without term frequencies, materialised as a relation.
    """
    uid = _uid()
    input_name = f"__ukam_input_addresses_{uid}"
    con.register(input_name, address_table)
    # For chunked processing, don't add ID yet - process chunks first
    total_rows = address_table.count("*").fetchone()[0]

    chunk_size = _calculate_chunk_size(total_rows, num_of_chunks)
    total_chunks = (total_rows + chunk_size - 1) // chunk_size

    con.execute(f"DROP TABLE IF EXISTS __ukam_chunked_addresses_{uid}")

    for chunk_index in range(total_chunks):
        chunk_started_at = time.perf_counter()
        chunk = con.sql(f"""
        SELECT *
            FROM {input_name}
            WHERE (abs(hash(address_concat)) % {total_chunks}) = {chunk_index}
        """)

        # Process the chunk without address ID, applying debug options only on first iteration
        processed_chunk = _clean_data_pre_term_frequencies(
            chunk,
            con,
            debug_options=debug_options if chunk_index == 0 else None,
        )

        if chunk_index == 0:
            processed_chunk.create(f"__ukam_chunked_addresses_{uid}")
        else:
            processed_chunk.insert_into(f"__ukam_chunked_addresses_{uid}")

        _log_progress(
            total_rows,
            min((chunk_index + 1) * chunk_size, total_rows),
            stage_type="Cleaned and preprocessed: ",
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            chunk_elapsed_seconds=time.perf_counter() - chunk_started_at,
        )

    return con.table(f"__ukam_chunked_addresses_{uid}")


def derive_term_frequencies_table(
    address_table: DuckDBPyRelation,
    con: DuckDBPyConnection,
    num_of_chunks: int = 10,
    *,
    debug_options: Optional["DebugOptions"] = None,
) -> DuckDBPyRelation:
    """Derive a term frequency lookup table from address data.

    This function cleans and tokenises addresses in chunks, then computes
    relative token frequencies from the combined result. The returned table
    can be passed to prepare_data_for_matching to ensure consistent term
    frequencies across multiple datasets.

    Example usage:
        tf_table = derive_term_frequencies_table(df_canonical, con)
        df_messy = prepare_data_for_matching(df_messy, con, term_frequency_lookup=tf_table)
        df_canonical = prepare_data_for_matching(df_canonical, con, term_frequency_lookup=tf_table)

    Args:
        address_table: Input address relation with address_concat column.
        con: DuckDB connection.
        num_of_chunks: Number of chunks to split the data into for cleaning.
            Set to 1 for no chunking.
        debug_options: Optional debug configuration for pipeline execution.

    Returns:
        Term frequency table with 'token' and 'rel_freq' columns.
    """
    uid = _uid()

    # Ensure postcode column exists
    address_table = _ensure_postcode_column(address_table)

    # Register input for chunked access
    input_name = f"__ukam_tf_derive_input_{uid}"
    con.register(input_name, address_table)

    total_rows = address_table.count("*").fetchone()[0]
    chunk_size = _calculate_chunk_size(total_rows, num_of_chunks)
    total_chunks = (total_rows + chunk_size - 1) // chunk_size

    cleaned_table = f"__ukam_tf_derive_cleaned_{uid}"
    con.execute(f"DROP TABLE IF EXISTS {cleaned_table}")

    # Process in chunks using minimal pipeline (clean + tokenise only)
    for chunk_index in range(total_chunks):
        chunk_started_at = time.perf_counter()
        chunk = con.sql(f"""
            SELECT *
            FROM {input_name}
            WHERE (abs(hash(address_concat)) % {total_chunks}) = {chunk_index}
        """)

        pipeline = create_sql_pipeline(
            con,
            input_rel=chunk,
            stage_specs=QUEUE_FOR_TF_DERIVATION,
            pipeline_name="Clean for TF derivation",
            pipeline_description="Clean and tokenise for term frequency computation",
        )
        processed_chunk = pipeline.run(debug_options if chunk_index == 0 else None)

        if chunk_index == 0:
            processed_chunk.create(cleaned_table)
        else:
            processed_chunk.insert_into(cleaned_table)

        _log_progress(
            total_rows,
            min((chunk_index + 1) * chunk_size, total_rows),
            stage_type="Cleaned for TF derivation: ",
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            chunk_elapsed_seconds=time.perf_counter() - chunk_started_at,
        )

    # Compute token frequencies from address_tokens
    tf_sql = f"""
    WITH unnested AS (
        SELECT unnest(address_tokens) AS token
        FROM {cleaned_table}
    )
    SELECT
        token,
        COUNT(*)::DOUBLE / (SELECT COUNT(*) FROM unnested) AS rel_freq
    FROM unnested
    GROUP BY token
    ORDER BY COUNT(*) DESC
    """

    # Materialise the result (consistent with parquet loading pattern)
    result_table = "__ukam_derived_term_frequencies"
    con.sql(f"DROP TABLE IF EXISTS {result_table}")
    con.sql(tf_sql).create(result_table)

    # Clean up intermediate table
    con.execute(f"DROP TABLE IF EXISTS {cleaned_table}")

    return con.table(result_table)


# Chunking this requires a three phase approach:
# 1. Clean data in chunks without term frequencies
# 2. Register term frequency tables (either provided or pre-baked)
# 3. Use term frequencies to populate term frequency fields in cleaned data and
#   finally apply QUEUE_POST_TF
def prepare_data_for_matching(
    address_table: DuckDBPyRelation,
    con: DuckDBPyConnection,
    num_of_chunks: int = 10,
    term_frequency_lookup: Optional[DuckDBPyRelation] = None,
    derive_distinguishing_wrt_adjacent_records: bool = False,
    *,
    debug_options: Optional[DebugOptions] = None,
) -> DuckDBPyRelation:
    """Prepare address data for matching.

    Args:
        address_table: Input address relation with standard schema.
        con: DuckDB connection.
        num_of_chunks: Number of chunks to split the data into. Term frequencies
            are applied from either the provided lookup table or pre-baked frequencies,
            then chunks are processed with those frequencies applied.
        term_frequency_lookup: Optional pre-computed term frequency table with
            'token' and 'rel_freq' columns. Use derive_term_frequencies_table()
            to create this from a reference dataset (typically the canonical addresses).
            If not provided, uses the package's pre-baked term frequencies.
        derive_distinguishing_wrt_adjacent_records: Whether to derive distinguishing
            tokens relative to adjacent records.
        debug_options: Optional debug configuration for pipeline execution.
            Note: Debug options are only applied on the first iteration to avoid
            excessive logging output.

    Returns:
        Cleaned address data with computed term frequencies, including numeric
        term frequency columns (tf_numeric_token_1, tf_numeric_token_2, tf_numeric_token_3).

    Example:
        # For consistent term frequencies across datasets:
        tf_table = derive_term_frequencies_table(df_canonical, con)
        df_messy = prepare_data_for_matching(df_messy, con, term_frequency_lookup=tf_table)
        df_canonical = prepare_data_for_matching(df_canonical, con, term_frequency_lookup=tf_table)

        # Using pre-baked term frequencies (default):
        df_prepared = prepare_data_for_matching(df_addresses, con)
    """
    uid = _uid()

    # Clean data in chunks (without term frequencies)
    cleaned_address_table = clean_data_pre_term_frequencies(
        address_table, con, num_of_chunks=num_of_chunks, debug_options=debug_options
    )

    total_rows = cleaned_address_table.count("*").fetchone()[0]
    _create_term_frequency_tables(con, term_frequency_lookup=term_frequency_lookup)

    chunk_size = _calculate_chunk_size(total_rows, num_of_chunks)
    total_chunks = (total_rows + chunk_size - 1) // chunk_size

    # Get the underlying table name for direct access
    cleaned_table_name = cleaned_address_table.alias

    # Apply term frequencies to cleaned chunks
    for chunk_index in range(total_chunks):
        chunk_started_at = time.perf_counter()
        chunk = con.sql(f"""
        SELECT *
            FROM {cleaned_table_name}
            WHERE (abs(hash(original_address_concat)) % {total_chunks}) = {chunk_index}
        """)

        # Numeric TF columns should only be attached when using precomputed TFs
        # If we are chunking, we want to precompute rel token freqs and then use them
        processed_chunk = _clean_data_using_precomputed_rel_tok_freq(
            chunk,
            con=con,
            pre_cleaned_addresses=True,
            derive_distinguishing_wrt_adjacent_records=derive_distinguishing_wrt_adjacent_records,
            debug_options=debug_options if chunk_index == 0 else None,
        )

        if chunk_index == 0:
            con.execute(f"DROP TABLE IF EXISTS __ukam_addresses_processed_{uid}")
            processed_chunk.create(f"__ukam_addresses_processed_{uid}")
        else:
            processed_chunk.insert_into(f"__ukam_addresses_processed_{uid}")

        # Delete processed rows from the intermediate cleaned table to free memory
        con.execute(f"""
            DELETE FROM {cleaned_table_name}
            WHERE (abs(hash(original_address_concat)) % {total_chunks}) = {chunk_index}
        """)

        _log_progress(
            total_rows,
            min((chunk_index + 1) * chunk_size, total_rows),
            stage_type="Applied term frequencies: ",
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            chunk_elapsed_seconds=time.perf_counter() - chunk_started_at,
        )

    # Verify the intermediate table is now empty (all chunks processed)
    remaining_rows = con.sql(f"SELECT COUNT(*) FROM {cleaned_table_name}").fetchone()[0]
    if remaining_rows != 0:
        raise ValueError(
            f"Expected intermediate table {cleaned_table_name} to be empty after processing, "
            f"but found {remaining_rows} rows remaining."
        )

    # Drop the now-empty intermediate table
    con.execute(f"DROP TABLE IF EXISTS {cleaned_table_name}")

    return con.table(f"__ukam_addresses_processed_{uid}")


__all__ = [
    "clean_data_pre_term_frequencies",
    "derive_term_frequencies_table",
    "prepare_data_for_matching",
]
