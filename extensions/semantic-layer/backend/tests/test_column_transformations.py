import ast
import threading
from types import SimpleNamespace

import pytest
from catalog_source import MODULES_PATH, api_class, compile_into, module_function

from text_to_bi.superset_semantic_layer.modules.business_model.exceptions import TransformEdgeNotHideableError
from text_to_bi.superset_semantic_layer.modules.business_model.services.layout import LINEAGE_EDGE_KEY
from text_to_bi.superset_semantic_layer.modules.business_model.services.lineage_overrides import (
    flipped_key,
    match_override,
)
from text_to_bi.superset_semantic_layer.modules.business_model.services.transformation_edges import (
    transformation_edges,
)
from text_to_bi.superset_semantic_layer.modules.data_dictionary.exceptions import (
    DataDictionaryValidationError,
    TransformationSourceMissingError,
)

LIVE_COLUMNS = {
    7: {"thanh_pho_id", "ten_thanh_pho"},
    9: {"quan_sat_id", "nhiet_do"},
    12: {"thanh_pho_key", "ten_thanh_pho", "nhiet_do_tb"},
}


def _constants(file_name: str) -> list[ast.Assign]:
    """The module-level limits of a data_dictionary service, which imports Superset and so cannot be imported here."""
    path = MODULES_PATH / "data_dictionary" / "services" / file_name
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id.isupper()]


def _checked_transformation():
    namespace = {"DataDictionaryValidationError": DataDictionaryValidationError}
    nodes = [*_constants("srv_transformation.py"), module_function("checked_transformation")]
    return compile_into(namespace, *nodes)["checked_transformation"]


def _columns_of(dataset_id):
    return LIVE_COLUMNS.get(dataset_id)


def test_a_transformation_keeps_its_expression_as_written_and_its_sources_in_order():
    checked = _checked_transformation()
    value = {
        "expression": "  AVG(tb_quan_sat.nhiet_do) theo ngày  ",
        "sources": [
            {"dataset_id": 9, "column_name": "nhiet_do"},
            {"dataset_id": 7, "column_name": "thanh_pho_id"},
            {"dataset_id": 9, "column_name": "nhiet_do"},
        ],
    }
    assert checked(value, "columns[0].transformation", (12, "nhiet_do_tb"), _columns_of) == {
        "expression": "AVG(tb_quan_sat.nhiet_do) theo ngày",
        "sources": [(9, "nhiet_do"), (7, "thanh_pho_id")],
    }
    copy = {"expression": "", "sources": [{"dataset_id": 7, "column_name": "ten_thanh_pho"}]}
    assert checked(copy, "t", (12, "ten_thanh_pho"), _columns_of) == {
        "expression": None,
        "sources": [(7, "ten_thanh_pho")],
    }
    assert checked(None, "t", (12, "ten_thanh_pho"), _columns_of) is None


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"expression": "x"}, "cần ít nhất một cột nguồn"),
        ({"expression": "x", "sources": []}, "cần ít nhất một cột nguồn"),
        ({"expression": 3, "sources": [{"dataset_id": 7, "column_name": "ten_thanh_pho"}]}, "expression phải là chuỗi"),
        ({"sources": [{"dataset_id": "7", "column_name": "ten_thanh_pho"}]}, "cần dataset_id và column_name"),
        ({"sources": [{"dataset_id": 12, "column_name": "nhiet_do_tb"}]}, "không thể là nguồn biến đổi của chính nó"),
        ({"sources": [{"dataset_id": 99, "column_name": "x"}]}, "Không tìm thấy dataset nguồn 99"),
        ({"sources": [{"dataset_id": 9, "column_name": "gio"}]}, "Không tìm thấy cột nguồn gio"),
        ({"sources": [], "formula": "x"}, "phải là object"),
        ("AVG(x)", "phải là object"),
    ],
)
def test_a_transformation_that_breaks_a_rule_is_refused_in_vietnamese(value, message):
    with pytest.raises(DataDictionaryValidationError, match=message):
        _checked_transformation()(value, "columns[0].transformation", (12, "nhiet_do_tb"), _columns_of)


def test_the_dictionary_save_checks_a_column_transformation_against_other_datasets():
    constants = [*_constants("srv_dictionary.py"), *_constants("srv_transformation.py")]
    lookups = []

    def get_dataset(dataset_id):
        lookups.append(dataset_id)
        columns = LIVE_COLUMNS.get(dataset_id)
        return None if columns is None else SimpleNamespace(columns=[SimpleNamespace(column_name=n) for n in columns])

    namespace = {
        "checked_column_semantics": lambda item, index, role: {},
        "checked_temporal_kind": lambda value, index: value,
        "get_dataset": get_dataset,
        "threading": threading,
        "DataDictionaryValidationError": DataDictionaryValidationError,
    }
    validate = compile_into(
        namespace, *constants, module_function("checked_transformation"), module_function("_checked_reference"), module_function("validate_dictionary_payload")
    )["validate_dictionary_payload"]
    source = {"dataset_id": 9, "column_name": "nhiet_do"}
    payload = {
        "columns": [
            {"column_name": "nhiet_do_tb", "transformation": {"expression": "AVG(nhiet_do)", "sources": [source]}},
            {"column_name": "ten_thanh_pho", "transformation": None},
            {"column_name": "thanh_pho_key", "transformation": {"sources": [source]}},
        ]
    }
    updates = validate(payload, LIVE_COLUMNS[12], 12)
    assert updates[0]["transformation"] == {"expression": "AVG(nhiet_do)", "sources": [(9, "nhiet_do")]}
    assert updates[1]["transformation"] is None
    assert lookups == [9]


class Repository:
    def __init__(self, stored=None, sources=()):
        self.stored = stored
        self.sources = list(sources)
        self.replaced = None
        self.deleted = None

    def get(self, column_id):
        return self.stored

    def sources_of(self, column_ids):
        return [(SimpleNamespace(source_column_id=source_id), None) for source_id in self.sources]

    def replace_sources(self, column_id, source_ids):
        self.replaced = source_ids

    def delete(self, entity):
        self.deleted = entity

    def add(self, entity):
        self.stored = entity
        return entity

    read = get
    read_sources = sources_of
    update_sources = replace_sources

    def create(self, column_id):
        return self.add(SimpleNamespace(column_id=column_id, expression=None))


def _save(repository, column_rows):
    namespace = {
        "column_transformation_repository": lambda: repository,
        "column_dictionary_repository": lambda: SimpleNamespace(
            read_by_column_name=lambda dataset_id, name: column_rows.get((dataset_id, name))
        ),
        "ColumnTransformation": lambda column_id: SimpleNamespace(column_id=column_id, expression=None),
    }
    return compile_into(namespace, module_function("save_transformation"))["save_transformation"]


def test_saving_a_transformation_stores_its_expression_and_source_rows():
    repository = Repository()
    rows = {(9, "nhiet_do"): SimpleNamespace(id=41), (7, "thanh_pho_id"): SimpleNamespace(id=12)}
    _save(repository, rows)(5, {"expression": "AVG(x)", "sources": [(9, "nhiet_do"), (7, "thanh_pho_id")]})
    assert repository.stored.column_id == 5 and repository.stored.expression == "AVG(x)"
    assert repository.replaced == [41, 12]


def test_an_unchanged_transformation_is_left_alone_and_none_removes_it():
    stored = SimpleNamespace(column_id=5, expression="AVG(x)")
    repository = Repository(stored, sources=[41])
    save = _save(repository, {(9, "nhiet_do"): SimpleNamespace(id=41)})
    save(5, {"expression": "AVG(x)", "sources": [(9, "nhiet_do")]})
    assert repository.replaced is None
    save(5, None)
    assert repository.replaced == [] and repository.deleted is stored


def test_a_source_column_without_a_dictionary_row_is_refused():
    with pytest.raises(TransformationSourceMissingError):
        _save(Repository(), {})(5, {"expression": None, "sources": [(9, "nhiet_do")]})


def _column(row_id, dataset_id, name):
    return SimpleNamespace(id=row_id, dataset_id=dataset_id, column_name=name)


def test_declared_transformations_draw_one_transform_edge_per_pair_of_tables():
    average = _column(1, 12, "nhiet_do_tb")
    city = _column(2, 12, "ten_thanh_pho")
    rows = [
        (average, "AVG(tb_quan_sat.nhiet_do)", _column(10, 9, "nhiet_do")),
        (average, "AVG(tb_quan_sat.nhiet_do)", _column(11, 7, "thanh_pho_id")),
        (average, "AVG(tb_quan_sat.nhiet_do)", _column(3, 12, "thanh_pho_key")),
        (city, None, _column(12, 7, "ten_thanh_pho")),
    ]
    names = {7: "dm_thanh_pho", 9: "tb_quan_sat", 12: "fact_thoi_tiet"}
    edges = transformation_edges(rows, names, LIVE_COLUMNS)
    assert set(edges) == {(9, 12, "transform"), (7, 12, "transform")}
    from_cities = edges[(7, 12, "transform")]
    assert from_cities["origin"] == "dictionary" and from_cities["label"] is None
    assert from_cities["column_links"] == [
        {"source": "thanh_pho_id", "target": "nhiet_do_tb"},
        {"source": "ten_thanh_pho", "target": "ten_thanh_pho"},
    ]
    # Each target column lists every input, even one from its own table that draws no edge.
    assert from_cities["transformations"] == [
        {
            "target_column": "nhiet_do_tb",
            "expression": "AVG(tb_quan_sat.nhiet_do)",
            "sources": ["tb_quan_sat.nhiet_do", "dm_thanh_pho.thanh_pho_id", "fact_thoi_tiet.thanh_pho_key"],
        },
        {"target_column": "ten_thanh_pho", "expression": None, "sources": ["dm_thanh_pho.ten_thanh_pho"]},
    ]
    assert edges[(9, 12, "transform")]["transformations"] == from_cities["transformations"][:1]


def test_columns_no_longer_in_superset_draw_no_transform_edge():
    rows = [
        (_column(1, 12, "dropped"), "x", _column(10, 9, "nhiet_do")),
        (_column(2, 12, "nhiet_do_tb"), "x", _column(11, 9, "renamed")),
    ]
    assert transformation_edges(rows, {9: "tb", 12: "fact"}, LIVE_COLUMNS) == {}


def test_a_transform_edge_keeps_its_key_and_its_overrides_when_layers_change():
    key = (9, 12, "transform")
    assert flipped_key(key) == key
    hidden = SimpleNamespace(is_hidden=True, is_manual=False)
    assert match_override(key, {key}, {key: hidden}) is hidden
    assert match_override(key, {key}, {(12, 9, "relation"): hidden}) is None
    assert LINEAGE_EDGE_KEY.match("transform-9-12")


class _ResponseAPI:
    def response(self, status, **payload):
        return status, payload


def _edge_removal_api(body, inferred):
    """remove_lineage_edge on fakes; `inferred` is what the Data Dictionary implies for datasets 9 and 12."""
    added, commits = [], []
    namespace = {
        "RestApi": _ResponseAPI,
        "require_admin": lambda: None,
        "ensure_dictionary_tables": lambda: None,
        "ensure_dataset_dictionaries": lambda datasets: None,
        "request": SimpleNamespace(get_json=lambda silent=True: body),
        "db": SimpleNamespace(session=SimpleNamespace(commit=lambda: commits.append(True), rollback=lambda: None)),
        "get_datasets": lambda ids: [SimpleNamespace(id=dataset_id) for dataset_id in ids],
        "infer_edges": lambda datasets: inferred,
        "find_edge_override": lambda key, inferred_edges: None,
        "lineage_edge_repository": lambda: SimpleNamespace(add=lambda row, flush=True: added.append(row)),
        # A class, since the route's annotations read `LineageEdge | None`.
        "LineageEdge": type("LineageEdge", (SimpleNamespace,), {}),
        "EDGE_KINDS": ("flow", "relation", "transform"),
    }
    compile_into(namespace, api_class({"remove_lineage_edge", "_edge_override", "_edge_key"}))
    return namespace["SemanticLayerAPI"](), added, commits


def test_a_declared_transform_edge_is_not_hidden_from_the_canvas():
    edge_key = {"source": 9, "target": 12, "kind": "transform"}
    api, added, commits = _edge_removal_api(edge_key, {(9, 12, "transform"): {}})
    assert api.remove_lineage_edge() == (400, {"message": TransformEdgeNotHideableError.message})
    assert added == [] and commits == []


def test_a_reference_edge_inferred_from_a_foreign_key_is_still_hidden():
    api, added, commits = _edge_removal_api({"source": 9, "target": 12, "kind": "flow"}, {(9, 12, "flow"): {}})
    assert api.remove_lineage_edge() == (200, {"source": 9, "target": 12, "kind": "flow"})
    assert [row.is_hidden for row in added] == [True] and commits == [True]


def _lineage_edges(edges, overrides):
    """services/business_model.py's lineage_edges, which imports Superset, run on fakes of what it reads."""
    path = MODULES_PATH / "business_model" / "services" / "business_model.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "lineage_edges")
    namespace = {
        "Any": object,
        "SqlaTable": object,
        "infer_edges": lambda datasets: edges,
        "lineage_edge_repository": lambda: SimpleNamespace(between=lambda datasets: overrides),
        "match_override": match_override,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return namespace["lineage_edges"]({})


def test_a_hidden_row_stored_earlier_for_a_transform_edge_no_longer_hides_it():
    edges = {
        (9, 12, "transform"): {"source": 9, "target": 12, "kind": "transform"},
        (7, 12, "flow"): {"source": 7, "target": 12, "kind": "flow"},
    }
    hidden = {"is_hidden": True, "is_manual": True, "color": None}
    overrides = [
        SimpleNamespace(id=1, source_dataset_id=9, target_dataset_id=12, kind="transform", **hidden),
        SimpleNamespace(id=2, source_dataset_id=7, target_dataset_id=12, kind="flow", **hidden),
    ]
    assert [(edge["source"], edge["kind"]) for edge in _lineage_edges(edges, overrides)] == [(9, "transform")]
