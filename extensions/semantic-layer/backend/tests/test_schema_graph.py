import json
from types import SimpleNamespace

from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_schema_graph import (
    GRAPH_VERSION,
    graph_edges,
    table_node,
)


def _live(name, type_="BIGINT", expression=None, is_active=True):
    return SimpleNamespace(column_name=name, type=type_, expression=expression, is_active=is_active, verbose_name=None)


def _entry(name, **fields):
    defaults = {
        "column_name": name,
        "display_name": name,
        "semantic_role": None,
        "aggregations": None,
        "synonyms": None,
        "description": None,
        "business_term": None,
        "unit": None,
        "temporal_kind": None,
        "is_pk": False,
        "is_unique": False,
        "is_fk": False,
    }
    return SimpleNamespace(**{**defaults, **fields})


def _contract(contract_id, source, target, status="approved"):
    return SimpleNamespace(
        id=contract_id,
        status=status,
        from_dataset_id=source,
        from_column="x_id",
        to_dataset_id=target,
        to_column="x_id",
        cardinality="many_to_one",
    )


def test_a_table_node_keeps_physical_columns_with_their_semantics():
    dataset = SimpleNamespace(
        id=15,
        schema="public",
        table_name="tb_quan_sat_thoi_tiet",
        description=None,
        columns=[
            _live("quan_sat_id"),
            _live("loai_quan_sat", "VARCHAR(30)"),
            _live("thoi_diem_quan_sat", "TIMESTAMP"),
            _live("ten_thanh_pho", "VARCHAR", expression="(SELECT ...)"),
            _live("cu", is_active=False),
        ],
    )
    dictionary = SimpleNamespace(
        display_name="Quan sát thời tiết",
        description="Một dòng một quan sát.",
        grain=None,
        time_column="thoi_diem_quan_sat",
        row_kind_column="loai_quan_sat",
        indicator_model=None,
    )
    entries = {
        "quan_sat_id": _entry("quan_sat_id", semantic_role="key", is_pk=True),
        "loai_quan_sat": _entry("loai_quan_sat", semantic_role="row_kind", synonyms=json.dumps(["loại quan sát"])),
    }
    grains = [SimpleNamespace(row_kind_value="DU_BAO_GIO", label="Dự báo theo giờ", grain="hour")]
    layer = SimpleNamespace(id=2, name="Nghiệp vụ", level=1)

    coded_values = {"loai_quan_sat": ["DU_BAO_GIO", "HIEN_TAI"]}
    node = table_node(dataset, dictionary, entries, grains, coded_values, None, None, layer)

    assert [column["name"] for column in node["columns"]] == ["quan_sat_id", "loai_quan_sat", "thoi_diem_quan_sat"]
    row_kind = node["columns"][1]
    assert (row_kind["role"], row_kind["synonyms"], row_kind["values"]) == (
        "row_kind",
        ["loại quan sát"],
        ["DU_BAO_GIO", "HIEN_TAI"],
    )
    assert node["columns"][2]["role"] is None and node["columns"][0]["is_pk"]
    assert node["time"]["row_kinds"] == [{"value": "DU_BAO_GIO", "label": "Dự báo theo giờ", "grain": "hour"}]
    assert node["layer"] == {"id": 2, "name": "Nghiệp vụ", "level": 1} and node["label"] == "Quan sát thời tiết"


def test_an_indicator_table_carries_its_declaration_and_indicators():
    model = {"kind": "values", "indicator_column": "chi_so_id", "value_columns": {"SO": "gia_tri_so"}}
    dictionary = SimpleNamespace(
        display_name=None,
        description=None,
        grain=None,
        time_column=None,
        row_kind_column=None,
        indicator_model=json.dumps(model),
    )
    dataset = SimpleNamespace(id=13, schema=None, table_name="tb_gia_tri_quan_sat", description=None, columns=[])

    node = table_node(dataset, dictionary, {}, [], {}, model, {"indicators": []}, None)

    assert node["indicator_model"] == model and node["indicators"] == {"indicators": []}
    assert node["label"] == "tb_gia_tri_quan_sat" and node["layer"] is None


def test_edges_follow_contract_order():
    edges = graph_edges([_contract(3, 15, 10), _contract(1, 13, 15)])

    assert [edge["id"] for edge in edges] == [1, 3]
    assert edges[0] == {
        "id": 1,
        "from": {"dataset_id": 13, "column": "x_id"},
        "to": {"dataset_id": 15, "column": "x_id"},
        "cardinality": "many_to_one",
    }


def test_tables_without_a_dictionary_keep_only_the_live_schema():
    dataset = SimpleNamespace(
        id=6,
        schema="public",
        table_name="dm_chi_so_thoi_tiet",
        columns=[_live("chi_so_id"), _live("display_name", expression="upper(name)"), _live("old", is_active=False)],
    )

    node = table_node(dataset, None, {}, [], {}, None, None, None)

    assert node["dataset_id"] == 6 and node["label"] == "dm_chi_so_thoi_tiet"
    assert node["description"] is None and node["time"]["column"] is None
    assert [column["name"] for column in node["columns"]] == ["chi_so_id"]
    assert node["layer"] is None and node["indicator_model"] is None and node["indicators"] is None


def test_edge_projection_serializes_only_the_contracts_passed_by_the_caller():
    current_contracts = [_contract(1, 13, 15)]

    edges = graph_edges(current_contracts)

    assert edges == [
        {
            "id": 1,
            "from": {"dataset_id": 13, "column": "x_id"},
            "to": {"dataset_id": 15, "column": "x_id"},
            "cardinality": "many_to_one",
        }
    ]
    assert GRAPH_VERSION == 1
