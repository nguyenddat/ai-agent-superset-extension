import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from text_to_bi.superset_text_to_bi import migrations
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import (
    ColumnDictionary,
    TableColumnRole,
    TableDictionary,
)

DICTIONARY_TABLES = {
    "table_dictionaries", "table_column_roles", "table_time_grains", "indicator_aggregations", "column_dictionaries",
    "column_aggregations", "column_synonyms",
}


def postgres_ddl(model):
    return str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))


def test_creates_the_data_dictionary_tables_once_per_process(env, monkeypatch):
    assert DICTIONARY_TABLES <= set(inspect(env.engine).get_table_names())
    calls = []
    original = migrations._migrate
    monkeypatch.setattr(migrations, "_tables_ready", False)
    monkeypatch.setattr(migrations, "_migrate", lambda: calls.append(original()))

    migrations.ensure_tables()
    migrations.ensure_tables()

    assert len(calls) == 1


def test_a_failed_migration_is_not_retried_for_thirty_seconds(env, monkeypatch):
    calls = []
    clock = [1000.0]

    def broken():
        calls.append(clock[0])
        raise RuntimeError("lock timeout")

    monkeypatch.setattr(migrations, "_tables_ready", False)
    monkeypatch.setattr(migrations, "_migrate", broken)
    monkeypatch.setattr(migrations.time, "monotonic", lambda: clock[0])

    with pytest.raises(RuntimeError, match="lock timeout"):
        migrations.ensure_tables()
    clock[0] += 29
    with pytest.raises(RuntimeError, match="failed recently"):
        migrations.ensure_tables()
    clock[0] += 2
    with pytest.raises(RuntimeError, match="lock timeout"):
        migrations.ensure_tables()
    assert len(calls) == 2


def test_postgres_tables_live_in_their_schema_and_follow_superset_datasets():
    table = postgres_ddl(TableDictionary)
    columns = postgres_ddl(ColumnDictionary)

    assert "CREATE TABLE text_to_bi.table_dictionaries" in table
    assert "FOREIGN KEY(dataset_id) REFERENCES tables (id) ON DELETE CASCADE" in table
    assert "FOREIGN KEY(created_by_fk) REFERENCES ab_user (id) ON DELETE SET NULL" in table
    assert "REFERENCES text_to_bi.table_dictionaries (id) ON DELETE SET NULL" in table
    assert "UNIQUE (dataset_id)" in table
    assert "id UUID NOT NULL" in table
    assert "FOREIGN KEY(dataset_id) REFERENCES tables (id) ON DELETE CASCADE" in columns
    assert "FOREIGN KEY(referenced_dataset_id) REFERENCES tables (id) ON DELETE SET NULL" in columns
    assert "UNIQUE (dataset_id, column_name)" in columns


def test_postgres_role_uniqueness_treats_a_missing_qualifier_as_one_value():
    index = next(index for index in TableColumnRole.__table__.indexes if index.unique)

    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert "ON text_to_bi.table_column_roles" in ddl
    assert "coalesce(qualifier, '')" in ddl
