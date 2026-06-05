from __future__ import annotations

import duckdb


def normalise_and_validate_raw_canonical(
    rel: duckdb.DuckDBPyRelation,
) -> duckdb.DuckDBPyRelation:
    """Normalise and validate required columns for raw canonical input."""
    if "address_concat" not in rel.columns and "original_address_concat" in rel.columns:
        rel = rel.project("*, original_address_concat AS address_concat")

    required = {"unique_id", "address_concat"}
    missing = sorted(required.difference(rel.columns))
    if missing:
        raise ValueError(
            "Canonical input is missing required columns: "
            f"{missing}. Expected at least ['address_concat', 'unique_id']."
        )

    return rel
