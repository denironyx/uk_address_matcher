from __future__ import annotations

import duckdb

from uk_address_matcher import (
    AddressMatcher,
    ExactMatchStage,
    SplinkStage,
    ukam_datasets,
)

con = duckdb.connect(database=":memory:")
messy, canonical = ukam_datasets.fictional_london

matcher = AddressMatcher(
    canonical_addresses=canonical,
    addresses_to_match=messy,
    con=con,
    stages=[
        ExactMatchStage(),
        SplinkStage(
            predict_threshold_match_weight=-20,
            final_match_weight_threshold=10,
            include_full_postcode_block=True,
        ),
    ],
)

match_result = matcher.match()

# Direct table output for SQL-derived threshold metrics.
accuracy_table = match_result.accuracy_analysis(
    output_type="table",
    add_metrics=["f1"],
)

# Direct chart-definition output for downstream rendering/storage.
precision_recall_chart = match_result.accuracy_analysis(
    output_type="precision_recall",
    add_metrics=["f1"],
)

threshold_selection_chart = match_result.accuracy_analysis(
    output_type="threshold_selection",
    add_metrics=["f1"],
)

precision_recall_chart
