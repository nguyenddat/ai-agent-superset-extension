import ast
import json
from pathlib import Path
from types import SimpleNamespace

from catalog_source import compile_into, module_function


def _is_internal_dataset():
    namespace = {"json": json, "SqlaTable": object, "INTERNAL_DATABASE_FLAG": "text_to_bi_internal"}
    compile_into(namespace, module_function("is_internal_dataset"))
    return namespace["is_internal_dataset"]


def _dataset(extra):
    return SimpleNamespace(database=SimpleNamespace(extra=extra))


def test_only_a_connection_flagged_internal_is_skipped():
    is_internal = _is_internal_dataset()

    assert is_internal(_dataset(json.dumps({"text_to_bi_internal": True})))
    assert not is_internal(_dataset(json.dumps({"text_to_bi_internal": "yes"})))
    assert not is_internal(_dataset(json.dumps({"engine_params": {}})))
    assert not is_internal(_dataset(None))
    assert not is_internal(_dataset("not json"))
    assert not is_internal(SimpleNamespace())


def test_every_all_dataset_listing_skips_internal_connections():
    package_path = Path(__file__).parents[1] / "src" / "text_to_bi" / "superset_semantic_layer" / "modules"
    dictionary_tree = ast.parse(
        (package_path / "data_dictionary" / "services" / "srv_dictionary.py").read_text(encoding="utf-8")
    )
    glossary_tree = ast.parse(
        (package_path / "glossary_management" / "services" / "srv_glossary_link.py").read_text(encoding="utf-8")
    )
    dictionary_methods = {
        node.name: node
        for class_node in dictionary_tree.body
        if isinstance(class_node, ast.ClassDef) and class_node.name == "DataDictionaryService"
        for node in class_node.body
        if isinstance(node, ast.FunctionDef)
    }
    dataset_listings = {
        "get_reference_options": dictionary_methods["read_reference_options"],
        "read_glossary_options": next(
            node for node in glossary_tree.body if isinstance(node, ast.FunctionDef) and node.name == "link_options"
        ),
    }

    for name, listing in dataset_listings.items():
        calls = {
            node.func.id
            for node in ast.walk(listing)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "is_internal_dataset" in calls, name
