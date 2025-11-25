from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from benchmarking.datasets.registry import DatasetInfo
from benchmarking.datasets.sources import SourceConfig, resolve_s3_path
from benchmarking.utils.io import load_duckdb_httpfs

if TYPE_CHECKING:
    import duckdb


HACKNEY_COUNCIL_INFO = DatasetInfo(
    name="Hackney Council",
    description="Council tax band records from Hackney Borough Council",
    source="S3: linking bucket (Hackney open data via Datadaptive)",
    notes="Open data council tax bands with ONSUD geocoding (July 2025)",
)

_HACKNEY_SOURCE = SourceConfig(
    name="hackney_council_tax",
    s3_key="HACKNEY_CTBANDS_ONSUD_202507.csv",
    unique_id_column="UPRN",
    postcode_column="POSTCODE",
    address_columns=["ADDR1", "ADDR2", "ADDR3", "ADDR4"],
)


@lru_cache(maxsize=None)
def get_hackney_council_data(
    con: duckdb.DuckDBPyConnection,
    sample_mode: bool = False,
) -> duckdb.DuckDBPyRelation:
    """Load Hackney council tax band data from S3.

    The CSV contains council tax band records with UPRN as the unique identifier.
    """
    load_duckdb_httpfs(con)

    base_path = resolve_s3_path("UKAM_HACKNEY_S3_BASE_PATH", "UKAM_HACKNEY_DATA_PATH")
    sql = _HACKNEY_SOURCE.select_statement(base_path)

    print(f"Reading Hackney dataset from S3: {base_path}{_HACKNEY_SOURCE.s3_key}")

    df_messy_raw = con.sql(sql)

    if sample_mode:
        df_messy_raw = con.sql(
            """
            SELECT * FROM df_messy_raw
            WHERE hash(unique_id) % 100 < 10
            ORDER BY unique_id
            LIMIT 10000
            """
        )

    return df_messy_raw
