from __future__ import annotations

from types import SimpleNamespace

import duckdb

from uk_address_matcher.sql_pipeline.helpers import _register_input_relation_once


class _FakeRelation:
    def __init__(self, sql: str) -> None:
        self._sql = sql
        self.alias = None

    def sql_query(self) -> str:
        return self._sql


class _FakeConnection:
    def __init__(self) -> None:
        self.register_calls: list[tuple[str, _FakeRelation]] = []
        self.sql_calls: list[str] = []
        self.table_calls: list[str] = []

    def execute(self, _query: str) -> SimpleNamespace:
        return SimpleNamespace(fetchone=lambda: (0,))

    def register(self, alias: str, relation: _FakeRelation) -> None:
        self.register_calls.append((alias, relation))

    def table(self, alias: str) -> _FakeRelation:
        self.table_calls.append(alias)
        return _FakeRelation("SELECT * FROM ColumnDataCollection - broken")

    def sql(self, query: str) -> _FakeRelation:
        self.sql_calls.append(query)
        return _FakeRelation(query)


def test_register_input_relation_once_uses_sql_for_registered_aliases():
    con = _FakeConnection()
    relation = _FakeRelation("SELECT 1 AS a")

    result = _register_input_relation_once(relation, con=con, role="probe")

    assert len(con.register_calls) == 1
    alias, registered_relation = con.register_calls[0]
    assert registered_relation is relation
    assert con.table_calls == []
    assert con.sql_calls == [f'SELECT * FROM "{alias}"']
    assert result.sql_query() == f'SELECT * FROM "{alias}"'


def test_register_input_relation_once_returns_nested_sql_for_cross_connection_relation():
    source_con = duckdb.connect(database=":memory:")
    target_con = duckdb.connect(database=":memory:")

    try:
        relation = source_con.sql(
            """
            SELECT *
            FROM (
                VALUES
                    (1, 'alpha'),
                    (2, 'beta')
            ) AS t(a, b)
            """
        )

        registered = _register_input_relation_once(
            relation,
            con=target_con,
            role="cross_connection",
        )

        target_con.execute(
            "CREATE TABLE registered_copy AS "
            f"SELECT * FROM ({registered.sql_query()}) AS src"
        )
        rows = target_con.table("registered_copy").order("a").fetchall()

        assert rows == [(1, "alpha"), (2, "beta")]
    finally:
        source_con.close()
        target_con.close()
