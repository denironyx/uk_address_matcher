from __future__ import annotations

from pathlib import Path

import duckdb

from scripts.generate_fictional_london_datasets import generate_fictional_datasets


def _payload_for_file(path: Path, include_label: bool) -> str:
    con = duckdb.connect(database=":memory:")
    if include_label:
        sql = f"""
        SELECT string_agg(
            unique_id || '|' || address_concat || '|' || postcode || '|' ||
            coalesce(ukam_label, ''),
            '\\n' ORDER BY unique_id
        )
        FROM read_parquet('{path.as_posix()}')
        """
    else:
        sql = f"""
        SELECT string_agg(
            unique_id || '|' || address_concat || '|' || postcode,
            '\\n' ORDER BY unique_id
        )
        FROM read_parquet('{path.as_posix()}')
        """
    return con.execute(sql).fetchone()[0]


def test_generate_fictional_london_datasets_deterministic_and_schema(tmp_path: Path):
    input_parquet = tmp_path / "input_source.parquet"
    out_1 = tmp_path / "out_1"
    out_2 = tmp_path / "out_2"

    con = duckdb.connect(database=":memory:")
    con.execute(
        f"""
        COPY (
            SELECT
                row_number() OVER () AS source_id,
                'row ' || CAST(row_number() OVER () AS VARCHAR) AS text_col
            FROM range(100)
        )
        TO '{input_parquet.as_posix()}'
        (FORMAT PARQUET)
        """
    )

    generate_fictional_datasets(
        input_parquet=input_parquet,
        output_dir=out_1,
        seed=12345,
        canonical_count=30,
        query_count=20,
        matchable_ratio=0.75,
    )
    generate_fictional_datasets(
        input_parquet=input_parquet,
        output_dir=out_2,
        seed=12345,
        canonical_count=30,
        query_count=20,
        matchable_ratio=0.75,
    )

    canonical_1 = out_1 / "fictional_london_canonical.parquet"
    query_1 = out_1 / "fictional_london_messy.parquet"
    canonical_2 = out_2 / "fictional_london_canonical.parquet"
    query_2 = out_2 / "fictional_london_messy.parquet"

    assert canonical_1.exists()
    assert query_1.exists()

    con = duckdb.connect(database=":memory:")
    canonical_columns = [
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{canonical_1.as_posix()}')"
        ).fetchall()
    ]
    query_columns = [
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{query_1.as_posix()}')"
        ).fetchall()
    ]

    assert canonical_columns == ["unique_id", "address_concat", "postcode"]
    assert query_columns == ["unique_id", "address_concat", "postcode", "ukam_label"]

    row_counts = con.execute(
        f"""
        SELECT
            (SELECT COUNT(*) FROM read_parquet('{canonical_1.as_posix()}')) AS canonical_count,
            (SELECT COUNT(*) FROM read_parquet('{query_1.as_posix()}')) AS query_count,
            (SELECT COUNT(*) FROM read_parquet('{query_1.as_posix()}') WHERE ukam_label IS NOT NULL)
                AS linked_count
        """
    ).fetchone()

    assert row_counts == (30, 20, 15)

    assert _payload_for_file(canonical_1, include_label=False) == _payload_for_file(
        canonical_2,
        include_label=False,
    )
    assert _payload_for_file(query_1, include_label=True) == _payload_for_file(
        query_2,
        include_label=True,
    )
