import duckdb
import pyarrow as pa
import pytest

from uk_address_matcher.post_linkage.match_result.result import (
    MatchResult,
    _build_threshold_metrics_sql,
)

# Sentinel values used by threshold metrics SQL for ±infinity
_NEG_INF = -999.0
_POS_INF = 999.0


def _run_threshold_metrics(
    matches: list[dict], canonical_ids: list[str]
) -> dict[float, dict]:
    """Register tables, run threshold-metrics SQL, return rows keyed by threshold."""
    con = duckdb.connect()
    con.register("__ukam_threshold_matches__", pa.Table.from_pylist(matches))
    con.register(
        "__ukam_threshold_canonical__",
        pa.Table.from_pylist([{"unique_id": uid} for uid in canonical_ids]),
    )
    rel = con.sql(_build_threshold_metrics_sql("m.match_weight"))
    cols = rel.columns
    rows = rel.fetchall()
    return {row[cols.index("truth_threshold")]: dict(zip(cols, row)) for row in rows}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_null_match_reason_maps_to_neg_inf():
    """NULL match_reason → truth_threshold of -999 (treated as −∞)."""
    rows = _run_threshold_metrics(
        matches=[
            {
                "unique_id": "a",
                "resolved_canonical_id": None,
                "ukam_label": "1",
                "match_weight": None,
                "match_reason": None,
            },
        ],
        canonical_ids=["1"],
    )
    assert _NEG_INF in rows


def test_deterministic_reasons_map_to_pos_inf():
    """All non-splink, non-NULL reasons → truth_threshold of +999 (treated as +∞)."""
    for reason in [
        "exact: full match",
        "peeled_address: match after removing common uk end tokens",
        "unique_trigram: unique trigram match",
    ]:
        rows = _run_threshold_metrics(
            matches=[
                {
                    "unique_id": "a",
                    "resolved_canonical_id": "1",
                    "ukam_label": "1",
                    "match_weight": None,
                    "match_reason": reason,
                },
            ],
            canonical_ids=["1"],
        )
        assert _POS_INF in rows, f"reason '{reason}' should map to +inf threshold"


def test_splink_match_uses_actual_weight():
    """Splink match_reason uses the real match_weight as the threshold."""
    rows = _run_threshold_metrics(
        matches=[
            {
                "unique_id": "a",
                "resolved_canonical_id": "1",
                "ukam_label": "1",
                "match_weight": 5.0,
                "match_reason": "splink: probabilistic match",
            },
        ],
        canonical_ids=["1"],
    )
    assert 5.0 in rows


def test_tp_fp_fn_tn_basic():
    """One exact TP, one splink TP, one true negative (no ukam_label).

    At threshold −999: all three rows are 'predicted positive'.
      Both labelled records match → TP=2; the unlabelled record → FP=1.
    At threshold 5.0 (splink weight): exact still above, splink at boundary.
      TP=2, FP=0, FN=0, TN=1.
    At threshold +999: only exact survives.
      TP=1, FP=0, FN=1 (splink match now below), TN=1.
    """
    rows = _run_threshold_metrics(
        matches=[
            {
                "unique_id": "a",
                "resolved_canonical_id": "1",
                "ukam_label": "1",
                "match_weight": None,
                "match_reason": "exact: full match",
            },
            {
                "unique_id": "b",
                "resolved_canonical_id": "2",
                "ukam_label": "2",
                "match_weight": 5.0,
                "match_reason": "splink: probabilistic match",
            },
            {
                "unique_id": "c",
                "resolved_canonical_id": None,
                "ukam_label": None,
                "match_weight": None,
                "match_reason": None,
            },
        ],
        canonical_ids=["1", "2"],
    )

    r = rows[_NEG_INF]
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2.0, 1.0, 0.0, 0.0)

    r = rows[5.0]
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2.0, 0.0, 0.0, 1.0)

    r = rows[_POS_INF]
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1.0, 0.0, 1.0, 1.0)


def test_wrong_canonical_match_uses_emitted_score():
    """Wrong canonical IDs keep the emitted splink score and count as FP.

    With top-1 semantics, wrong-ID rows are false positives at their emitted
    score (not floored to -999), while recall is still reduced because TP/P
    stays below 1.
    """
    rows = _run_threshold_metrics(
        matches=[
            {
                "unique_id": "e",
                "resolved_canonical_id": "1",
                "ukam_label": "1",
                "match_weight": None,
                "match_reason": "exact: full match",
            },
            {
                "unique_id": "a",
                "resolved_canonical_id": "2",
                "ukam_label": "1",
                "match_weight": 8.0,
                "match_reason": "splink: probabilistic match",
            },
        ],
        canonical_ids=["1", "2"],
    )

    assert 8.0 in rows
    r = rows[8.0]
    assert r["tp"] == 1.0
    assert r["fp"] == 1.0
    assert r["fn"] == 1.0

    r = rows[_POS_INF]
    assert r["tp"] == 1.0
    assert r["fp"] == 0.0


def test_label_without_canonical_is_not_a_false_negative():
    """A ukam_label with no corresponding canonical record is not matchable,
    so an unmatched result is a TN, not a FN.

    A second record with a real splink score anchors a threshold above -999,
    at which the unmatchable record falls into TN.
    """
    rows = _run_threshold_metrics(
        matches=[
            {
                "unique_id": "a",
                "resolved_canonical_id": None,
                "ukam_label": "99",
                "match_weight": None,
                "match_reason": None,
            },  # "99" not in canonical
            {
                "unique_id": "b",
                "resolved_canonical_id": "1",
                "ukam_label": "1",
                "match_weight": 5.0,
                "match_reason": "splink: probabilistic match",
            },
        ],
        canonical_ids=["1"],
    )

    # At threshold 5.0, record 'a' (score=-999) is predicted negative; its label
    # has no canonical entry so it is clerical_negative → TN, not FN.
    r = rows[5.0]
    assert r["fn"] == 0.0
    assert r["tn"] == 1.0


def test_wrong_match_threshold_transition_fp_then_fn_only():
    """A wrong-ID splink decision transitions from FP+FN to FN-only as threshold rises.

    Why this is correct under top-1 record-level evaluation:

    - At thresholds that ACCEPT the wrong decision score, we emit a wrong match,
      so the record contributes a false positive; and because TP is still not
      achieved for that labelled positive, it also contributes to false negatives
      via FN = P - TP.
    - At thresholds ABOVE the wrong score, the wrong decision is rejected,
      removing the false positive, but the true link is still unrecovered,
      so it remains a false negative.
    """
    rows = _run_threshold_metrics(
        matches=[
            {
                "unique_id": "good",
                "resolved_canonical_id": "1",
                "ukam_label": "1",
                "match_weight": None,
                "match_reason": "exact: full match",
            },
            {
                "unique_id": "wrong",
                "resolved_canonical_id": "2",
                "ukam_label": "1",
                "match_weight": 15.0,
                "match_reason": "splink: probabilistic match",
            },
        ],
        canonical_ids=["1", "2"],
    )

    # Equivalent to using threshold > 14 (decision score 15 is accepted)
    r = rows[15.0]
    assert r["tp"] == 1.0
    assert r["fp"] == 1.0
    assert r["fn"] == 1.0

    # Equivalent to using threshold > 16 (score 15 is rejected)
    # represented by the next higher threshold bucket (+999)
    r = rows[_POS_INF]
    assert r["tp"] == 1.0
    assert r["fp"] == 0.0
    assert r["fn"] == 1.0


def test_accuracy_analysis_rejects_roc_output_type():
    con = duckdb.connect()
    con.register(
        "m",
        pa.Table.from_pylist(
            [
                {
                    "unique_id": "a",
                    "resolved_canonical_id": "1",
                    "ukam_label": "1",
                    "match_weight": None,
                    "match_reason": "exact: full match",
                }
            ]
        ),
    )
    con.register("c", pa.Table.from_pylist([{"unique_id": "1"}]))

    result = MatchResult(
        _relation=con.table("m"),
        con=con,
        _canonical_relation=con.table("c"),
    )

    with pytest.raises(ValueError, match="Invalid output_type"):
        result.accuracy_analysis(output_type="roc")
