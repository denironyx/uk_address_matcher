import duckdb
import pyarrow


from uk_address_matcher import (
    run_matching,
    ExactMatchStage,
    UniqueTrigramStage,
    SplinkStage,
    improve_predictions_using_distinguishing_tokens,
    prepare_data_for_matching,
    get_linker,
    evaluate_predictions_against_labels,
    best_matches_with_distinguishability,
    derive_term_frequencies_table,
    derive_inverted_index,
)

from uk_address_matcher.cleaning.chunking_strategies import (
    prepare_data_for_matching,
)
from uk_address_matcher.sql_pipeline.runner import DebugOptions

available_deterministic_stages = [ExactMatchStage, UniqueTrigramStage]
con = duckdb.connect(database=":memory:")

uprns = [
    "100010539337",
    "100010539947",
    "100010541018",
    "100010539331",
    "100010539332",
    "100010539333",
]
uprns = "(" + ",".join(uprns) + ")"
df_os = (
    con.read_parquet(
        "/Users/robin.linacre/Documents/data_linking/build_abp_for_address_matching_documented/data_old/output/abp_for_uk_address_matcher.*.parquet"
    )
    .filter(f"uprn IN {uprns}")
    .select("postcode, address_concat.lower() as address_concat, uprn as unique_id")
)


USE_LABELS = True
messy_data = [
    {
        # Exact match
        "unique_id": "A1",
        "address_concat": "1 churchill road preston pr2 6xt ",
        "postcode": "PR26XT",
        "ukam_label": "100010539331",
    },
    {
        # Trigram match
        "unique_id": "A2",
        "address_concat": "12 colwyn place ingol pr2 3yd",
        "postcode": "",
        "ukam_label": "100010539946",
    },
    {
        # Fuzzy match
        "unique_id": "A3",
        "address_concat": "92 cromwell preston pr2 6ye",
        "postcode": "PR2 6YE",
        "ukam_label": "100010541018",
    },
    {
        # No match
        "unique_id": "A4",
        "address_concat": "1 high street london sw1a 1aa",
        "postcode": "SW1A 1AA",
        "ukam_label": "ABC",
    },
]

if not USE_LABELS:
    for record in messy_data:
        record.pop("ukam_label")

pyarrow_table = pyarrow.Table.from_pylist(messy_data)
df_messy = con.from_arrow(pyarrow_table)


tf_table = derive_term_frequencies_table(df_os, con=con)


df_os_clean = prepare_data_for_matching(
    df_os, con=con, term_frequency_lookup=tf_table, num_of_chunks=5
)
df_os_clean

inverted_index = derive_inverted_index(
    df_os_clean,
    con=con,
    # debug_options=debug_options,
)


df_messy_clean = prepare_data_for_matching(
    df_messy,
    con=con,
    inverted_index=inverted_index,
    term_frequency_lookup=tf_table,
    # debug_options=debug_options,
)


debug_options = DebugOptions(
    pretty_print_sql=True,
    debug_mode=True,
    debug_show_sql=True,
    debug_incremental=True,
    debug_max_rows=2,
)

match_candidates = run_matching(
    con=con,
    df_messy_clean=df_messy_clean,
    df_canonical_clean=df_os_clean,
    stages=[
        ExactMatchStage(),
        UniqueTrigramStage(),
        SplinkStage(
            predict_threshold_match_weight=-50,
            improve_threshold_match_weight=-20,
            final_match_weight_threshold=15,
            final_distinguishability_threshold=None,
            include_full_postcode_block=True,
            additional_columns_to_retain=["original_address_concat"],
            retain_intermediate_calculation_columns=True,
        ),
    ],
)
match_candidates.show(max_width=5000)
match_candidates

# match_candidates.show(max_width=500, max_rows=20)


evaluation_results_rel = evaluate_predictions_against_labels(
    match_candidates=match_candidates,
    con=con,
)

evaluation_results_rel
