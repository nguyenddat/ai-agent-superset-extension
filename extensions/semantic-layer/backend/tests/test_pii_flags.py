import ast
import threading
from types import SimpleNamespace

import pytest
from catalog_source import MODULES_PATH, compile_into, module_function
from test_glossary_bootstrap import _migration_namespace

from text_to_bi.superset_semantic_layer.modules.data_dictionary.exceptions import DataDictionaryValidationError
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_pii import checked_pii_flag, mark_catalog_pii


def test_a_pii_mark_is_true_or_false():
    assert checked_pii_flag(True, "dataset.contains_pii") is True
    assert checked_pii_flag(False, "columns[0].contains_pii") is False
    for value in (None, 1, "true", 0):
        with pytest.raises(DataDictionaryValidationError, match="columns\\[2\\].contains_pii phải là true hoặc false."):
            checked_pii_flag(value, "columns[2].contains_pii")


def _dictionary_constants() -> list[ast.Assign]:
    """The module-level field lists of services/dictionary.py, which imports Superset and so cannot be imported here."""
    tree = ast.parse((MODULES_PATH / "data_dictionary" / "services" / "srv_dictionary.py").read_text(encoding="utf-8"))
    return [node for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id.isupper()]


def test_a_column_save_carries_its_pii_mark_and_refuses_anything_but_a_boolean():
    namespace = {
        "checked_pii_flag": checked_pii_flag,
        "checked_column_semantics": lambda item, index, role: {},
        "checked_temporal_kind": lambda value, index: value,
        "get_dataset": lambda dataset_id: None,
        "threading": threading,
    }
    validate = compile_into(
        namespace, *_dictionary_constants(), module_function("_checked_reference"),
        module_function("validate_dictionary_payload"),
    )[
        "validate_dictionary_payload"
    ]
    columns = {"owner_phone", "station"}
    payload = {"columns": [{"column_name": "owner_phone", "contains_pii": True}, {"column_name": "station"}]}
    expected = [{"column_name": "owner_phone", "contains_pii": True}, {"column_name": "station"}]
    assert validate(payload, columns, 7) == expected
    with pytest.raises(DataDictionaryValidationError, match="contains_pii"):
        validate({"columns": [{"column_name": "station", "contains_pii": "yes"}]}, columns, 7)


def test_the_dictionary_returns_the_pii_marks_of_the_dataset_and_its_columns():
    record = SimpleNamespace(
        id=11, column_name="owner_phone", display_name="Số điện thoại", nullable=True, default_value=None, is_pk=False,
        is_fk=False, referenced_column=None, is_unique=False, unit=None, format=None, business_term=None,
        temporal_kind=None, semantic_role="attribute", aggregations=None, synonyms=None, description=None,
        contains_pii=True,
    )
    dictionary = SimpleNamespace(
        display_name="Trạm", description=None, grain=None, create_column=None, dataset_type="base", layer_id=None,
        time_column=None, row_kind_column=None, indicator_model=None, contains_pii=True,
    )
    live_column = SimpleNamespace(column_name="owner_phone", type="TEXT")
    dataset = SimpleNamespace(id=7, table_name="dm_tram", columns=[live_column])
    namespace = {
        "SqlaTable": object,
        "DatasetDictionary": object,
        "ColumnDictionary": object,
        "column_dictionary_repository": lambda: SimpleNamespace(read_by_ids=lambda ids: []),
        "dataset_grain_repository": lambda: SimpleNamespace(read_by_row_kind=lambda dataset_id: []),
        "get_datasets": lambda dataset_ids: [],
        "stored_indicator_model": lambda value: None,
        "stored_transformations": lambda column_ids: {},
        "is_admin": lambda: True,
    }
    serialize = compile_into(namespace, module_function("serialize_dictionary"))["serialize_dictionary"]
    payload = serialize(dataset, dictionary, [record])
    assert payload["contains_pii"] is True and payload["columns"][0]["contains_pii"] is True


def test_the_catalog_says_which_datasets_and_dimensions_hold_pii():
    datasets = [
        {"id": 7, "dimensions": [{"name": "station"}, {"name": "owner_phone"}]},
        {"id": 8, "dimensions": [{"name": "day"}]},
    ]
    mark_catalog_pii(datasets, {7: True}, {(7, "owner_phone"): True, (7, "station"): False})
    assert datasets[0]["contains_pii"] is True
    assert [dimension["contains_pii"] for dimension in datasets[0]["dimensions"]] == [False, True]
    assert datasets[1]["contains_pii"] is False and datasets[1]["dimensions"][0]["contains_pii"] is False


def test_the_migration_adds_a_pii_column_to_both_dictionaries_when_missing():
    namespace = _migration_namespace()
    # This migration covers legacy metric definitions and is outside the PII columns asserted here.
    namespace["_root_metrics_on_definition"] = lambda _postgres: None
    statements = []
    existing_columns = {}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, parameters=None):
            statements.append(str(statement))
            return SimpleNamespace(scalars=list, all=list)

    namespace["db"].engine.begin = lambda: Connection()
    namespace["inspect"] = lambda _engine: SimpleNamespace(
        get_columns=lambda name: [{"name": column} for column in existing_columns.get(name, [])],
        get_indexes=lambda _name: [],
        has_table=lambda _name: False,
    )
    compile_into(namespace, module_function("_migrate_dictionary_tables"))
    namespace["_migrate_dictionary_tables"]()
    added = [statement for statement in statements if "contains_pii" in statement]
    assert added == [
        "ALTER TABLE DatasetDictionary ADD COLUMN contains_pii BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE ColumnDictionary ADD COLUMN contains_pii BOOLEAN NOT NULL DEFAULT FALSE",
    ]

    statements.clear()
    existing_columns.update(DatasetDictionary=["contains_pii"], ColumnDictionary=["contains_pii"])
    namespace["_migrate_dictionary_tables"]()
    assert not [statement for statement in statements if "contains_pii" in statement]
