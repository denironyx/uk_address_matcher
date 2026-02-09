from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from uk_address_matcher.sql_pipeline.helpers import _uid

if TYPE_CHECKING:
    import duckdb

    from uk_address_matcher.sql_pipeline.runner import DebugOptions


_REQUIRED_COLUMNS = {
    "ukam_address_id",
    "canonical_ukam_address_id",
    "resolved_canonical_id",
}


class MatchingStage(ABC):
    """Base class for deterministic matching stages."""

    @abstractmethod
    def find_matches(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_name: str,
        df_unmatched: duckdb.DuckDBPyRelation,
        df_canonical: duckdb.DuckDBPyRelation,
        debug_options: Optional[DebugOptions] = None,
        explain: bool = False,
    ) -> Optional[duckdb.DuckDBPyRelation]:
        """Return matches for currently unmatched records."""

    def run(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_name: str,
        results_table: str,
        df_unmatched: duckdb.DuckDBPyRelation,
        df_canonical: duckdb.DuckDBPyRelation,
        debug_options: Optional[DebugOptions] = None,
        explain: bool = False,
    ) -> None:
        """Run this stage and write matched rows into the shared results table."""
        stage_matches = self.find_matches(
            con=con,
            stage_name=stage_name,
            df_unmatched=df_unmatched,
            df_canonical=df_canonical,
            debug_options=debug_options,
            explain=explain,
        )

        if explain or stage_matches is None:
            return

        missing = _REQUIRED_COLUMNS - set(stage_matches.columns)
        if missing:
            missing_str = ", ".join(sorted(missing))
            raise ValueError(
                f"Stage '{stage_name}' result missing required columns: {missing_str}"
            )

        self._write_matches_to_results(
            con=con,
            stage_name=stage_name,
            results_table=results_table,
            stage_matches=stage_matches,
        )

    def _write_matches_to_results(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_name: str,
        results_table: str,
        stage_matches: duckdb.DuckDBPyRelation,
    ) -> None:
        tmp_table = f"__ukam_stage_matches_{_uid()}"
        match_reason_expr = (
            "match_reason"
            if "match_reason" in stage_matches.columns
            else f"'{stage_name}' AS match_reason"
        )

        con.execute(f"DROP TABLE IF EXISTS {tmp_table}")
        con.execute(
            f"""
            CREATE TABLE {tmp_table} AS
            SELECT
                ukam_address_id,
                canonical_ukam_address_id,
                resolved_canonical_id,
                {match_reason_expr},
                * EXCLUDE (
                    ukam_address_id,
                    canonical_ukam_address_id,
                    resolved_canonical_id,
                    match_reason
                )
            FROM ({stage_matches.sql_query()})
            WHERE resolved_canonical_id IS NOT NULL
            """
        )

        temp_columns = con.execute(f"DESCRIBE SELECT * FROM {tmp_table}").fetchall()
        temp_column_types = {row[0]: row[1] for row in temp_columns}

        results_columns = {
            row[1] for row in con.execute(f"PRAGMA table_info('{results_table}')").fetchall()
        }

        additional_columns = [
            col
            for col in temp_column_types
            if col
            not in {
                "ukam_address_id",
                "canonical_ukam_address_id",
                "resolved_canonical_id",
                "match_reason",
            }
        ]

        for column_name in additional_columns:
            if column_name not in results_columns:
                column_type = temp_column_types[column_name]
                con.execute(
                    f"ALTER TABLE {results_table} ADD COLUMN {column_name} {column_type}"
                )

        set_clauses = [
            "canonical_ukam_address_id = src.canonical_ukam_address_id",
            "resolved_canonical_id = src.resolved_canonical_id",
            "match_reason = src.match_reason",
        ]
        set_clauses.extend(
            f"{column_name} = src.{column_name}" for column_name in additional_columns
        )
        set_sql = ",\n                ".join(set_clauses)

        con.execute(
            f"""
            UPDATE {results_table} AS dst
            SET
                {set_sql}
            FROM {tmp_table} AS src
            WHERE dst.ukam_address_id = src.ukam_address_id
              AND dst.resolved_canonical_id IS NULL
            """
        )

        con.execute(f"DROP TABLE IF EXISTS {tmp_table}")
