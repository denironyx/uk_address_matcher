from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from uk_address_matcher.linking_model.exact_matching.resolve_with_trigrams import (
    _resolve_with_trigrams,
)
from uk_address_matcher.linking_model.matching.input_filters import (
    _restrict_canonical_to_messy_postcodes,
)
from uk_address_matcher.linking_model.matching.stages._sql_helpers import run_sql_pipeline
from uk_address_matcher.linking_model.matching.stages.base_stage import MatchingStage

if TYPE_CHECKING:
    import duckdb

    from uk_address_matcher.sql_pipeline.runner import DebugOptions


@dataclass(frozen=True)
class UniqueTrigramStage(MatchingStage):
    """Match unresolved records using unique trigram evidence."""

    ngram_size: int = 3
    min_unique_hits: int = 1
    include_conflicts: bool = False
    include_trigram_text: bool = True

    def find_matches(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_name: str,
        df_unmatched: duckdb.DuckDBPyRelation,
        df_canonical: duckdb.DuckDBPyRelation,
        debug_options: Optional[DebugOptions] = None,
        explain: bool = False,
    ) -> Optional[duckdb.DuckDBPyRelation]:
        return run_sql_pipeline(
            con=con,
            pipeline_stages=[
                _restrict_canonical_to_messy_postcodes("exact"),
                _resolve_with_trigrams(
                    ngram_size=self.ngram_size,
                    min_unique_hits=self.min_unique_hits,
                    include_conflicts=self.include_conflicts,
                    include_trigram_text=self.include_trigram_text,
                ),
            ],
            stage_name=stage_name,
            df_unmatched=df_unmatched,
            df_canonical=df_canonical,
            debug_options=debug_options,
            explain=explain,
        )
