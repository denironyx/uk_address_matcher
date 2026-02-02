from typing import Optional

from duckdb import DuckDBPyConnection, DuckDBPyRelation


from uk_address_matcher.cleaning.steps import (
    _add_term_frequencies_to_address_tokens_using_registered_df,
    _add_ukam_address_id,
    _canonicalise_postcode,
    _clean_address_string_first_pass,
    _clean_address_string_second_pass,
    _extract_postcode_from_address,
    _first_unusual_token,
    _generalised_token_aliases,
    _get_token_frequeny_table,
    _move_common_end_tokens_to_field,
    _normalise_abbreviations_and_units,
    _parse_out_business_unit,
    _parse_out_flat_position_and_letter,
    _parse_out_numbers,
    _remove_duplicate_end_tokens,
    _rename_and_select_columns,
    _separate_distinguishing_start_tokens_from_with_respect_to_adjacent_records,
    _separate_unusual_tokens,
    _split_numeric_tokens_to_cols,
    _tokenise_address_without_numbers,
    _trim_whitespace_address_and_postcode,
    _upper_case_address_and_postcode,
    _use_first_unusual_token_if_no_numeric_token,
)
from uk_address_matcher.cleaning.steps.term_frequencies import (
    _attach_numeric_term_frequencies,
    _create_histograms_from_token_frequencies,
)
from uk_address_matcher.cleaning.steps.tokenisation import (
    _create_tokenised_address_concat,
)
from uk_address_matcher.sql_pipeline.helpers import package_resource_read_sql
from uk_address_matcher.sql_pipeline.runner import DebugOptions, create_sql_pipeline


def _ensure_postcode_column(rel: DuckDBPyRelation) -> DuckDBPyRelation:
    """Ensure the relation has a postcode column, adding NULL if missing.

    Handles case-insensitive matching (e.g., 'PostCode', 'POSTCODE', 'postcode').
    """
    # Check for postcode column case-insensitively
    columns_lower = [col.lower() for col in rel.columns]

    if "postcode" in columns_lower:
        # Find the actual column name (might be PostCode, POSTCODE, etc.)
        postcode_col = [col for col in rel.columns if col.lower() == "postcode"][0]

        if postcode_col != "postcode":
            # Rename to lowercase and ensure VARCHAR type
            return rel.select(
                f"* EXCLUDE ({postcode_col}), CAST({postcode_col} AS VARCHAR) AS postcode"
            )
        else:
            # Already lowercase, just ensure VARCHAR type
            return rel.select(
                "* EXCLUDE (postcode), CAST(postcode AS VARCHAR) AS postcode"
            )
    else:
        # No postcode column exists, add NULL
        return rel.select("*, CAST(NULL AS VARCHAR) AS postcode")


QUEUE_CLEAN_FULL_ADDRESS = [
    _add_ukam_address_id,
    _extract_postcode_from_address,
    _rename_and_select_columns,
    _trim_whitespace_address_and_postcode,
    _upper_case_address_and_postcode,
    _canonicalise_postcode,
    _clean_address_string_first_pass,
    _normalise_abbreviations_and_units,
    _remove_duplicate_end_tokens,  # clean_full_address now completed
]


QUEUE_DERIVE_NON_TF_FEATURES = [
    _create_tokenised_address_concat,  # based on clean_full_address
    _parse_out_flat_position_and_letter,
    _parse_out_business_unit,
    _parse_out_numbers,
    _clean_address_string_second_pass,
    _split_numeric_tokens_to_cols,
    _tokenise_address_without_numbers,
]


QUEUE_PRE_TF = [
    *QUEUE_CLEAN_FULL_ADDRESS,
    *QUEUE_DERIVE_NON_TF_FEATURES,
]


QUEUE_PRE_TF_WITH_DISTINGUISHING_WRT_ADJACENT = [
    *QUEUE_CLEAN_FULL_ADDRESS,
    _separate_distinguishing_start_tokens_from_with_respect_to_adjacent_records,
    _generalised_token_aliases,
    *QUEUE_DERIVE_NON_TF_FEATURES,
]

QUEUE_POST_TF = [
    _move_common_end_tokens_to_field,
    _first_unusual_token,
    _use_first_unusual_token_if_no_numeric_token,
    _separate_unusual_tokens,
    _create_histograms_from_token_frequencies,
    _attach_numeric_term_frequencies,
]


def _clean_data_with_minimal_steps(
    address_table: DuckDBPyRelation,
    con: DuckDBPyConnection,
    *,
    debug_options: Optional[DebugOptions] = None,
) -> DuckDBPyRelation:
    # Ensure postcode column exists before pipeline entry
    address_table = _ensure_postcode_column(address_table)
    pipeline = create_sql_pipeline(
        con,
        input_rel=address_table,
        stage_specs=QUEUE_PRE_TF,
        pipeline_name="Clean data with minimal steps",
        pipeline_description="A minimal cleaning pipeline without term frequencies",
    )
    result = pipeline.run(debug_options)

    # Exclude source_dataset column if present (will be overwritten by linker)
    if "source_dataset" in result.columns:
        con.register("__temp_result_for_exclude", result)
        result = con.sql(
            "SELECT * EXCLUDE (source_dataset) FROM __temp_result_for_exclude"
        )

    return result


def _clean_data_using_precomputed_rel_tok_freq(
    address_table: DuckDBPyRelation,
    con: DuckDBPyConnection,
    derive_distinguishing_wrt_adjacent_records: bool = False,
    *,
    pre_cleaned_addresses: bool = False,
    additional_stages: list = [],
    debug_options: Optional[DebugOptions] = None,
) -> DuckDBPyRelation:
    # Ensure postcode column exists before pipeline entry
    if not pre_cleaned_addresses:
        address_table = _ensure_postcode_column(address_table)
    pre_queue = (
        QUEUE_PRE_TF_WITH_DISTINGUISHING_WRT_ADJACENT
        if derive_distinguishing_wrt_adjacent_records
        else QUEUE_PRE_TF
    )

    tf_and_post = [
        _add_term_frequencies_to_address_tokens_using_registered_df
    ] + QUEUE_POST_TF
    stage_queue = (
        pre_queue + tf_and_post + additional_stages
        if not pre_cleaned_addresses
        else tf_and_post + additional_stages
    )

    pipeline = create_sql_pipeline(
        con,
        address_table,
        stage_queue,
        pipeline_name="Clean data using precomputed term frequencies",
        pipeline_description=(
            "Clean address data using a supplied table of relative token frequencies"
        ),
    )
    result = pipeline.run(debug_options)

    # Exclude source_dataset column if present (will be overwritten by linker)
    if "source_dataset" in result.columns:
        con.register("__temp_result_for_exclude", result)
        result = con.sql(
            "SELECT * EXCLUDE (source_dataset) FROM __temp_result_for_exclude"
        )

    return result


def get_numeric_term_frequencies_from_address_table(
    df_address_table: DuckDBPyRelation,
    con: DuckDBPyConnection,
    *,
    pre_cleaned_addresses: bool = False,
    debug_options: Optional[DebugOptions] = None,
) -> DuckDBPyRelation:
    stage_queue = [
        _rename_and_select_columns,
        _trim_whitespace_address_and_postcode,
        _upper_case_address_and_postcode,
        _clean_address_string_first_pass,
        _parse_out_flat_position_and_letter,
        _parse_out_numbers,
    ]

    if not pre_cleaned_addresses:
        pipeline = create_sql_pipeline(
            con,
            df_address_table,
            stage_queue,
            pipeline_name="Get numeric term frequencies",
            pipeline_description=(
                "Derive numeric tokens and compute frequency distribution"
            ),
        )
        numeric_tokens_rel = pipeline.run(debug_options)
        con.register("numeric_tokens_df", numeric_tokens_rel)
    else:
        con.register("numeric_tokens_df", df_address_table)

    sql = """
    with unnested as (
        select unnest(numeric_tokens) as numeric_token
        from numeric_tokens_df
    )
    select
        numeric_token,
        count(*)/(select count(*) from unnested) as tf_numeric_token
    from unnested
    group by numeric_token
    order by 2 desc
    """
    return con.sql(sql)


def get_address_token_frequencies_from_address_table(
    df_address_table: DuckDBPyRelation,
    con: DuckDBPyConnection,
    *,
    pre_cleaned_addresses: bool = False,
    debug_options: Optional[DebugOptions] = None,
) -> DuckDBPyRelation:
    stage_queue = [
        _rename_and_select_columns,
        _trim_whitespace_address_and_postcode,
        _upper_case_address_and_postcode,
        _clean_address_string_first_pass,
        _parse_out_flat_position_and_letter,
        _parse_out_numbers,
        _clean_address_string_second_pass,
        _split_numeric_tokens_to_cols,
        _tokenise_address_without_numbers,
        _get_token_frequeny_table,
    ]
    if pre_cleaned_addresses:
        stage_queue = stage_queue[-1:]  # only need the last step if pre-cleaned

    pipeline = create_sql_pipeline(
        con,
        df_address_table,
        stage_queue,
        pipeline_name="Get address token frequencies",
        pipeline_description=("Tokenise addresses and compute frequency distribution"),
    )
    return pipeline.run(debug_options)


def _create_term_frequency_tables(
    cleaned_address_table: DuckDBPyRelation,
    con: DuckDBPyConnection,
    # Default is to use precomputed term frequencies
    use_data_specific_term_frequencies: bool | None = False,
    *,
    pre_cleaned_addresses: bool = True,
) -> tuple[DuckDBPyRelation, DuckDBPyRelation, str]:
    """Compute and register address and numeric term frequency tables."""
    # Compute or load address token frequencies
    if use_data_specific_term_frequencies:
        address_token_frequencies_rel = (
            get_address_token_frequencies_from_address_table(
                cleaned_address_table, con, pre_cleaned_addresses=pre_cleaned_addresses
            )
        )

        # Compute numeric term frequencies
        numeric_term_frequencies_rel = get_numeric_term_frequencies_from_address_table(
            cleaned_address_table, con, pre_cleaned_addresses=pre_cleaned_addresses
        )
        con.sql("DROP TABLE IF EXISTS __ukam_numeric_term_frequencies")
        numeric_term_frequencies_rel.create("__ukam_numeric_term_frequencies")

    else:
        read_tf_sql = package_resource_read_sql(
            "uk_address_matcher.data", "address_token_frequencies.parquet"
        )
        address_token_frequencies_rel = con.sql(read_tf_sql)

        # Load precomputed numeric term frequencies as well
        read_numeric_tf_sql = package_resource_read_sql(
            "uk_address_matcher.data", "numeric_token_frequencies.parquet"
        )
        numeric_term_frequencies_rel = con.sql(read_numeric_tf_sql)
        con.sql("DROP TABLE IF EXISTS __ukam_numeric_term_frequencies")
        numeric_term_frequencies_rel.create("__ukam_numeric_term_frequencies")

    # Materialise the term frequency table to avoid lazy evaluation issues
    # when the underlying data is modified or dropped
    con.sql("DROP TABLE IF EXISTS __ukam_rel_tok_freq")
    address_token_frequencies_rel.create("__ukam_rel_tok_freq")
    con.register("rel_tok_freq", con.table("__ukam_rel_tok_freq"))
    return con.table("__ukam_rel_tok_freq")
