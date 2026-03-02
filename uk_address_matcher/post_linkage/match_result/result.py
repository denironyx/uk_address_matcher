from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal

from duckdb import DuckDBPyConnection, DuckDBPyRelation

from uk_address_matcher.post_linkage.analyse_results import (
    calculate_match_metrics,
)
from uk_address_matcher.post_linkage.match_result.splink_inspector import (
    _SplinkInspector,
)

_SPLINK_MATCH_REASON = "splink: probabilistic match"


def _build_roc_sql(rounding_expr: str) -> str:
    """Return the ROC truth-space SQL, parameterised by the score-rounding expression."""
    return f"""
    WITH canonical_ids AS (
        SELECT DISTINCT unique_id FROM __ukam_roc_canonical__
    ),
    labelled AS (
        SELECT
            m.unique_id,
            CASE WHEN c.unique_id IS NOT NULL THEN 1 ELSE 0 END AS clerical_positive,
            CASE
                -- No correct canonical exists: score their actual model decision.
                WHEN c.unique_id IS NULL THEN
                    CASE
                        WHEN m.match_reason IS NULL THEN CAST(-999 AS DOUBLE)
                        WHEN m.match_reason = '{_SPLINK_MATCH_REASON}' THEN {rounding_expr}
                        ELSE CAST(999 AS DOUBLE)
                    END
                -- Correct canonical exists and we matched to it: score their confidence.
                WHEN m.resolved_canonical_id = m.ukam_label THEN
                    CASE
                        WHEN m.match_reason IS NULL THEN CAST(-999 AS DOUBLE)
                        WHEN m.match_reason = '{_SPLINK_MATCH_REASON}' THEN {rounding_expr}
                        ELSE CAST(999 AS DOUBLE)
                    END
                -- Correct canonical exists but we missed or mis-matched: count as lowest score.
                ELSE CAST(-999 AS DOUBLE)
            END AS match_weight_adj
        FROM __ukam_roc_matches__ m
        LEFT JOIN canonical_ids c ON m.ukam_label = c.unique_id
    ),
    grouped AS (
        SELECT
            match_weight_adj                             AS truth_threshold,
            COUNT(*)                                     AS n,
            SUM(clerical_positive)                       AS cp,
            SUM(1 - clerical_positive)                   AS cn
        FROM labelled
        GROUP BY match_weight_adj
    ),
    stats AS (
        SELECT
            truth_threshold,
            SUM(cp) OVER (ORDER BY truth_threshold DESC)                AS cum_tp,
            SUM(cn) OVER (ORDER BY truth_threshold ASC)  - cn           AS cum_tn,
            SUM(cp) OVER ()                                             AS total_p,
            SUM(cn) OVER ()                                             AS total_n,
            SUM(n)  OVER (ORDER BY truth_threshold DESC)                AS n_at_or_above,
            SUM(n)  OVER (ORDER BY truth_threshold ASC)  - n           AS n_below
        FROM grouped
    ),
    truth_space AS (
        SELECT
            truth_threshold,
            total_p                                      AS P,
            total_n                                      AS N,
            CAST(cum_tp                    AS DOUBLE)    AS TP,
            CAST(cum_tn                    AS DOUBLE)    AS TN,
            CAST(n_at_or_above - cum_tp    AS DOUBLE)    AS FP,
            CAST(n_below       - cum_tn    AS DOUBLE)    AS FN
        FROM stats
    )
    SELECT
        truth_threshold,
        CASE
            WHEN truth_threshold >=  999 THEN 1.0
            WHEN truth_threshold <= -999 THEN 0.0
            ELSE power(2, truth_threshold) / (1.0 + power(2, truth_threshold))
        END                                                             AS match_probability,
        TP                                                              AS tp,
        TN                                                              AS tn,
        FP                                                              AS fp,
        FN                                                              AS fn,
        TP / NULLIF(P, 0)                                               AS tp_rate,
        TN / NULLIF(N, 0)                                               AS tn_rate,
        FP / NULLIF(N, 0)                                               AS fp_rate,
        FN / NULLIF(P, 0)                                               AS fn_rate,
        CASE WHEN TP + FP = 0 THEN 1.0 ELSE TP / (TP + FP) END         AS precision,
        TP / NULLIF(P, 0)                                               AS recall,
        CASE
            WHEN 2.0 * TP + FP + FN = 0 THEN 0.0
            ELSE 2.0 * TP / (2.0 * TP + FP + FN)
        END                                                             AS f1
    FROM truth_space
    ORDER BY truth_threshold ASC
    """


@dataclass
class MatchResult:
    """Wraps match output with connection-scoped inspection helpers.

    Access the underlying DuckDB relation via `.matches()`.

    Key methods:
        match_metrics      - match-reason breakdown with counts and percentages.
        match_reasons      - distinct match-reason values.
        splink_predictions - raw Splink predictions table (requires `SplinkStage`).
    """

    _relation: DuckDBPyRelation
    con: DuckDBPyConnection
    _splink_linker: Any | None = None
    _canonical_relation: DuckDBPyRelation | None = None
    _splink_inspector: _SplinkInspector | None = None

    def __post_init__(self) -> None:
        if self._splink_linker is not None:
            self._splink_inspector = _SplinkInspector(
                con=self.con,
                linker=self._splink_linker,
            )

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return (
            f"{class_name} object.\n"
            "Use .matches() to retrieve your raw results as a DuckDB table."
        )

    def matches(self, *, all_columns: bool = False) -> DuckDBPyRelation:
        """The underlying DuckDB relation containing match results.

        Args:
            all_columns: When True, return every column. By default only the
                key result columns are returned.
        """
        if all_columns:
            return self._relation
        preferred = [
            "unique_id",
            "resolved_canonical_id",
            "ukam_label",
            "original_address_concat",
            "original_address_concat_canonical",
            "match_reason",
            "match_weight",
            "distinguishability",
        ]
        available = set(self._relation.columns)
        cols = [c for c in preferred if c in available]
        return self._relation.select(*cols)

    def match_metrics(
        self,
        *,
        order: Literal["descending", "ascending"] = "descending",
    ) -> DuckDBPyRelation:
        """Match-reason breakdown with counts and percentages"""

        return calculate_match_metrics(self._relation, order=order)

    def _has_splink(self) -> bool:
        """True when a Splink stage ran and inspection helpers are available."""
        return self._splink_linker is not None

    def _require_splink(self) -> _SplinkInspector:
        """Return the Splink inspector or raise if unavailable."""
        if self._splink_inspector is None:
            raise ValueError(
                "Splink inspection is unavailable. Run a Splink stage to enable it."
            )
        return self._splink_inspector

    def splink_predictions(
        self,
        limit: int | None = None,
        ukam_ids: list[str | int] | None = None,
        *,
        threshold_match_probability: float | None = None,
        threshold_match_weight: float | None = None,
    ) -> DuckDBPyRelation:
        """Splink predictions as a DuckDB relation.

        Use ``ukam_ids`` to filter on the input-side identifier.
        """
        return self._require_splink().predictions(
            limit=limit,
            ukam_ids=ukam_ids,
            threshold_match_probability=threshold_match_probability,
            threshold_match_weight=threshold_match_weight,
        )

    def roc_data(
        self,
        *,
        match_weight_round_to_nearest: float | None = 0.1,
    ) -> list[dict]:
        """Compute ROC truth-space metrics swept over every match-weight threshold.

        Each row in the returned list corresponds to one threshold value and
        contains the confusion-matrix counts (tp, tn, fp, fn) plus the derived
        rates (tp_rate, fp_rate, precision, recall, f1) used to plot a ROC curve.

        The ground-truth positive class is determined by looking up each record's
        ``ukam_label`` in the canonical dataset.  A record whose ``ukam_label``
        matches a canonical ``unique_id`` is treated as an expected match;
        all others are treated as expected non-matches.

        The score used as the decision threshold is:

        - ``+999`` for non-splink matches (exact, peeled, trigram) — treated as
          certainty, but only when the canonical was matched correctly.
        - The actual ``match_weight`` for splink probabilistic matches.
        - ``-999`` for unmatched records or records matched to the wrong
          canonical — treated as the lowest possible confidence.

        Args:
            match_weight_round_to_nearest: Round splink match weights to this
                increment before grouping to reduce the number of threshold
                points.  Pass ``None`` to keep full precision.  Defaults to 0.1.

        Returns:
            List of dicts with keys: ``truth_threshold``, ``match_probability``,
            ``tp``, ``tn``, ``fp``, ``fn``, ``tp_rate``, ``tn_rate``,
            ``fp_rate``, ``fn_rate``, ``precision``, ``recall``, ``f1``.
        """
        if "ukam_label" not in self._relation.columns:
            raise ValueError(
                "roc_data requires a 'ukam_label' column in the match results. "
                "Add a ground-truth label column to the input addresses_to_match data."
            )
        if self._canonical_relation is None:
            raise ValueError(
                "roc_data requires access to the canonical dataset to determine "
                "the ground-truth positive class.  This is set automatically when "
                "matching via AddressMatcher."
            )

        if match_weight_round_to_nearest is not None:
            rounding_expr = (
                f"CAST({match_weight_round_to_nearest} AS DOUBLE) "
                f"* round(m.match_weight / {match_weight_round_to_nearest})"
            )
        else:
            rounding_expr = "m.match_weight"

        sql = _build_roc_sql(rounding_expr)

        self.con.register("__ukam_roc_matches__", self._relation)
        self.con.register("__ukam_roc_canonical__", self._canonical_relation)
        try:
            rel = self.con.sql(sql)
            rows = rel.fetchall()
            cols = rel.columns
        finally:
            self.con.unregister("__ukam_roc_matches__")
            self.con.unregister("__ukam_roc_canonical__")

        return [dict(zip(cols, row)) for row in rows]

    def accuracy_analysis(
        self,
        *,
        match_weight_round_to_nearest: float | None = 0.1,
        output_type: Literal[
            "threshold_selection", "roc", "precision_recall", "table"
        ] = "threshold_selection",
        add_metrics: List[
            Literal["specificity", "npv", "accuracy", "f1", "f2", "f0_5", "p4", "phi"]
        ] = [],
    ) -> Any:
        """Generate an accuracy chart or table from labelled match results.

        Mirrors Splink's ``linker.evaluation.accuracy_analysis_from_labels_table``
        API.  Requires a ``ukam_label`` column in the input addresses.

        Args:
            match_weight_round_to_nearest: Round splink match weights to this
                increment before grouping.  Pass ``None`` for full precision.
                Defaults to 0.1.
            output_type: One of:

                - ``"threshold_selection"`` *(default)* — interactive panel
                  showing precision/recall curves against match-weight threshold.
                - ``"roc"`` — ROC curve (false positive rate vs true positive rate).
                - ``"precision_recall"`` — precision vs recall curve.
                - ``"table"`` — the raw truth-space data as a list of dicts.

            add_metrics: Extra metrics to include in the ``"threshold_selection"``
                chart.  Accepted values: ``"specificity"``, ``"npv"``,
                ``"accuracy"``, ``"f1"``, ``"f2"``, ``"f0_5"``, ``"p4"``, ``"phi"``.

        Returns:
            An Altair chart, or a list of dicts when ``output_type="table"``.
        """
        from splink.internals.charts import (
            precision_recall_chart as _splink_pr_chart,
            roc_chart as _splink_roc_chart,
            threshold_selection_tool as _splink_threshold_tool,
        )

        records = self.roc_data(
            match_weight_round_to_nearest=match_weight_round_to_nearest
        )

        if output_type == "threshold_selection":
            return _splink_threshold_tool(records, add_metrics=add_metrics)
        elif output_type == "roc":
            return _splink_roc_chart(records)
        elif output_type == "precision_recall":
            return _splink_pr_chart(records)
        elif output_type == "table":
            return records
        else:
            raise ValueError(
                "Invalid output_type. Allowed values are: "
                "'threshold_selection', 'roc', 'precision_recall', 'table'."
            )

    def _splink_waterfall_chart(
        self,
        records: Any,
        *,
        filter_nulls: bool = True,
        remove_sensitive_data: bool = False,
        as_dict: bool = False,
    ) -> Any:
        """Splink waterfall chart for prediction records.

        ``records`` must match the structure returned by Splink's
        ``as_record_dict``. DuckDB relations and Splink prediction dataframes
        are converted to dictionaries automatically.

        Requires ``retain_intermediate_calculation_columns=True`` on your
        ``SplinkStage`` so that the comparison-vector columns needed by the
        waterfall are present in the predictions table.
        """
        self._require_splink()
        record_dicts = _ensure_record_dicts(records)

        try:
            return self._splink_linker.visualisations.waterfall_chart(
                record_dicts,
                filter_nulls=filter_nulls,
                remove_sensitive_data=remove_sensitive_data,
                as_dict=as_dict,
            )
        except ValueError as e:
            if "retain_intermediate_calculation_columns" in str(e):
                raise ValueError(
                    "Waterfall charts require "
                    "retain_intermediate_calculation_columns=True on your "
                    "SplinkStage. For example:\n\n"
                    "    SplinkStage(\n"
                    "        retain_intermediate_calculation_columns=True,\n"
                    "        ...\n"
                    "    )"
                ) from e
            raise


def _ensure_record_dicts(records: Any) -> list[dict[str, Any]]:
    if isinstance(records, DuckDBPyRelation):
        rows = records.fetchall()
        columns = records.columns
        return [dict(zip(columns, row)) for row in rows]
    if hasattr(records, "as_record_dict"):
        return records.as_record_dict()
    if isinstance(records, list):
        if not records:
            return records
        if isinstance(records[0], dict):
            return records
    raise TypeError(
        "Waterfall charts expect a DuckDB relation, a Splink predictions "
        "dataframe with as_record_dict(), or a list of record dictionaries."
    )
