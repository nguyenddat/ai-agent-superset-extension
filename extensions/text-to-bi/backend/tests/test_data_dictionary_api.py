import pytest
from sqlalchemy import select
from support import EDITOR, QUERY, VIEWER, call_route, column, database, dataset

from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import TableDictionary
from text_to_bi.superset_text_to_bi.modules.data_dictionary.routes.route_data_dictionary import DataDictionaryAPI

API = DataDictionaryAPI


@pytest.fixture
def warehouse(env):
    source, other, internal = database(1, "Warehouse"), database(2, "Other"), database(3, "Governance", internal=True)
    datasets = {
        "orders": dataset(1, "orders", [
            column("id", "BIGINT"), column("customer_id", "BIGINT"), column("amount", "NUMERIC(12, 2)"),
            column("order_date", "DATE", is_dttm=True), column("status", "VARCHAR(20)"),
            column("created_at", "TIMESTAMP WITHOUT TIME ZONE", is_dttm=True),
        ], source, description="Đơn"),
        "customers": dataset(2, "customers", [column("id", "BIGINT")], source),
        "values": dataset(
            3, "metric_values", [column("metric_id", "BIGINT"), column("value_number", "NUMERIC")], source,
        ),
        "catalog": dataset(4, "metric_catalog", [
            column("metric_id", "BIGINT"), column("code", "VARCHAR(50)"), column("name", "VARCHAR(100)"),
            column("aggregation", "VARCHAR(20)"),
        ], source),
        "elsewhere": dataset(5, "elsewhere", [column("id", "BIGINT")], other, schema="sales"),
        "questions": dataset(6, "question_log", [column("id", "BIGINT")], internal),
    }
    env.add_datasets(*datasets.values())
    return datasets


def get_dictionary(env, dataset_id):
    return call_route(env.app, API.get_dataset_dictionary, dataset_id=dataset_id)


def put_table(env, item, **body):
    payload = {"display_name": item.table_name, **body}
    return call_route(env.app, API.save_table_dictionary, "PUT", payload, dataset_id=item.id)


def reference(dataset_id, column_name):
    return {"dataset_id": dataset_id, "column_name": column_name}


def put_columns(env, item, columns):
    return call_route(env.app, API.save_column_dictionaries, "PUT", {"columns": columns}, dataset_id=item.id)


def test_unsaved_dictionary_returns_defaults(env, warehouse):
    response = get_dictionary(env, 1)

    assert response.status == 200
    body = response.json
    assert (body["is_saved"], body["can_edit"], body["dataset_kind"]) == (False, True, "physical")
    assert (body["display_name"], body["description"], body["layout"]) == ("orders", "Đơn", "wide")
    assert (body["database_name"], body["schema_name"]) == ("Warehouse", "public")
    assert all(item["semantic_role_is_default"] for item in body["columns"])
    assert {item["column_name"]: item["semantic_role"] for item in body["columns"]} == {
        "id": "key", "customer_id": "key", "amount": "measure", "order_date": "time", "status": "dimension",
        "created_at": "time",
    }
    kinds = {item["column_name"]: item["temporal_kind"] for item in body["columns"]}
    assert (kinds["order_date"], kinds["created_at"], kinds["amount"]) == ("date", "timestamp", None)
    assert get_dictionary(env, 99).json == {
        "code": "dataset_not_found", "message": "Không tìm thấy dataset được yêu cầu.",
    }
    assert get_dictionary(env, 99).status == 404


def test_verbose_name_and_temporal_flag_come_from_superset(env, warehouse):
    events = dataset(7, "events", [
        column("happened_on", "VARCHAR(10)", is_dttm=True),
        column("user_key", "VARCHAR(32)", verbose_name="Người dùng"),
    ], warehouse["orders"].database)
    env.add_datasets(events)

    columns = {item["column_name"]: item for item in get_dictionary(env, 7).json["columns"]}

    assert (columns["happened_on"]["temporal_kind"], columns["happened_on"]["semantic_role"]) == ("timestamp", "time")
    assert (columns["user_key"]["display_name"], columns["user_key"]["semantic_role"]) == ("Người dùng", "key")


def test_save_table_dictionary_with_roles_and_grains(env, warehouse):
    response = put_table(
        env, warehouse["orders"], display_name=" Đơn hàng ", grain_description="Một đơn hàng", table_kind="base",
        contains_pii=True, column_roles=[
            {"role": "time", "column_name": "order_date"}, {"role": "created_at", "column_name": "created_at"},
        ],
        time_grains=[{"time_grain": "day", "label": "Theo ngày"}],
    )

    assert response.status == 200, response.json
    body = response.json
    assert (body["is_saved"], body["display_name"], body["contains_pii"]) == (True, "Đơn hàng", True)
    assert {role["role"]: role["column_name"] for role in body["column_roles"]} == {
        "time": "order_date", "created_at": "created_at",
    }
    assert body["time_grains"] == [{"row_kind_value": None, "label": "Theo ngày", "time_grain": "day"}]
    stored = env.session.scalar(select(TableDictionary))
    assert (stored.dataset_id, stored.created_by_fk, stored.changed_by_fk, stored.id.version) == (1, 1, 1, 7)

    replaced = put_table(env, warehouse["orders"], column_roles=[], time_grains=[]).json
    assert (replaced["column_roles"], replaced["time_grains"], replaced["contains_pii"]) == ([], [], False)


@pytest.mark.parametrize("body", [
    {"table_kind": "fact"},
    {"layout": "matrix"},
    {"column_roles": [{"role": "catalog_key", "column_name": "id"}]},
    {"column_roles": [{"role": "time", "column_name": "missing"}]},
    {"column_roles": [{"role": "time", "qualifier": "number", "column_name": "order_date"}]},
    {"time_grains": [{"time_grain": "decade"}]},
    {"time_grains": [{"time_grain": "day", "row_kind_value": "daily"}]},
    {"time_grains": [{"time_grain": "day"}, {"time_grain": "hour"}]},
    {"layout": "indicator_values"},
    {"indicator_aggregations": [{"source_code": "SUM", "aggregation": "SUM"}]},
    {"indicator_catalog_dataset_id": 4},
    {"column_roles": [{"role": "row_kind", "column_name": "status"}], "time_grains": [{"time_grain": "day"}]},
])
def test_table_dictionary_validation(env, warehouse, body):
    response = put_table(env, warehouse["orders"], **body)

    assert response.status == 422, response.json
    assert set(response.json) == {"code", "message"}
    assert response.json["code"] == "invalid_data_dictionary"
    assert get_dictionary(env, 1).json["is_saved"] is False


@pytest.mark.parametrize("payload", [
    {"display_name": ""},
    {"display_name": "Đơn", "unknown": True},
    {"display_name": "Đơn", "column_roles": [{"role": "time"}]},
    None,
])
def test_a_malformed_body_is_422_with_a_safe_message(env, warehouse, payload):
    response = call_route(env.app, API.save_table_dictionary, "PUT", payload, dataset_id=1)

    assert (response.status, response.json) == (422, {
        "code": "invalid_request", "message": "Dữ liệu yêu cầu không hợp lệ.",
    })


def test_indicator_layouts(env, warehouse):
    catalog = put_table(env, warehouse["catalog"], layout="indicator_catalog", column_roles=[
        {"role": "catalog_key", "column_name": "metric_id"}, {"role": "catalog_code", "column_name": "code"},
        {"role": "catalog_name", "column_name": "name"}, {"role": "catalog_aggregation", "column_name": "aggregation"},
    ], indicator_aggregations=[{"source_code": "TONG", "aggregation": "SUM"}])
    assert catalog.status == 200, catalog.json
    values_body = {
        "layout": "indicator_values", "indicator_catalog_dataset_id": 4,
        "column_roles": [
            {"role": "indicator_key", "column_name": "metric_id"},
            {"role": "value", "qualifier": "number", "column_name": "value_number"},
        ],
    }
    values = put_table(env, warehouse["values"], **values_body)
    assert values.status == 200, values.json
    assert values.json["indicator_catalog"] == {
        "dataset_id": 4, "schema_name": "public", "table_name": "metric_catalog", "display_name": "metric_catalog",
    }

    assert put_table(env, warehouse["catalog"]).status == 200
    assert get_dictionary(env, 3).json["indicator_catalog"] is None
    assert put_table(env, warehouse["values"], **values_body).status == 422


def test_save_column_dictionaries(env, warehouse):
    response = put_columns(env, warehouse["orders"], [
        {
            "column_name": "amount", "display_name": "Tổng tiền", "unit": "VND", "aggregations": ["SUM", "AVG", "SUM"],
            "synonyms": ["doanh thu", "Doanh Thu", " doanh số ", ""],
        },
        {
            "column_name": "customer_id", "display_name": "Khách hàng", "semantic_role": "key",
            "referenced_column": {"dataset_id": 2, "column_name": "id"},
        },
        {"column_name": "status", "display_name": "Trạng thái", "is_primary_key": False},
    ])

    assert response.status == 200, response.json
    columns = {item["column_name"]: item for item in response.json["columns"]}
    assert columns["amount"]["aggregations"] == ["SUM", "AVG"]
    assert columns["amount"]["synonyms"] == ["doanh thu", "doanh số"]
    assert columns["customer_id"]["referenced_column"] == {
        "dataset_id": 2, "schema_name": "public", "table_name": "customers", "column_name": "id",
    }
    assert (columns["customer_id"]["semantic_role"], columns["customer_id"]["semantic_role_is_default"]) == (
        "key", False,
    )
    assert columns["amount"]["semantic_role_is_default"] is True
    assert columns["id"]["is_saved"] is False

    updated = put_columns(env, warehouse["orders"], [
        {"column_name": "amount", "display_name": "Tổng tiền", "synonyms": ["doanh thu thuần"]},
    ]).json
    amount = next(item for item in updated["columns"] if item["column_name"] == "amount")
    assert (amount["aggregations"], amount["synonyms"]) == ([], ["doanh thu thuần"])


@pytest.mark.parametrize("item", [
    {"column_name": "missing", "display_name": "x"},
    {"column_name": "amount", "display_name": "x", "semantic_role": "metric"},
    {"column_name": "amount", "display_name": "x", "temporal_kind": "time"},
    {"column_name": "status", "display_name": "x", "aggregations": ["SUM"]},
    {"column_name": "customer_id", "display_name": "x", "aggregations": ["SUM"]},
    {"column_name": "amount", "display_name": "x", "aggregations": ["MEDIAN"]},
    {"column_name": "amount", "display_name": "x", "referenced_column": {"dataset_id": 1, "column_name": "amount"}},
    {"column_name": "amount", "display_name": "x", "referenced_column": {"dataset_id": 5, "column_name": "id"}},
    {"column_name": "amount", "display_name": "x", "referenced_column": {"dataset_id": 2, "column_name": "code"}},
    {"column_name": "amount", "display_name": "x", "synonyms": [f"s{i}" for i in range(21)]},
    {"column_name": "amount", "display_name": " "},
])
def test_column_dictionary_validation(env, warehouse, item):
    assert put_columns(env, warehouse["orders"], [item]).status == 422


def test_column_dictionary_rejects_a_repeated_column_and_an_unreadable_reference(env, warehouse):
    amount = {"column_name": "amount", "display_name": "x"}
    assert put_columns(env, warehouse["orders"], [amount, amount]).status == 422

    env.catalog.denied.add(2)
    reference = {**amount, "referenced_column": {"dataset_id": 2, "column_name": "id"}}
    assert put_columns(env, warehouse["orders"], [reference]).status == 422


def test_summary_groups_readable_datasets_by_database_and_schema(env, warehouse):
    put_table(env, warehouse["orders"], display_name="Đơn hàng")
    put_columns(env, warehouse["orders"], [
        {"column_name": "id", "display_name": "Mã đơn"}, {"column_name": "amount", "display_name": "Giá trị"},
    ])
    put_columns(env, warehouse["customers"], [{"column_name": "id", "display_name": "Mã khách"}])

    response = call_route(env.app, API.get_summary)

    assert response.status == 200
    summary = response.json
    assert (summary["table_count"], summary["described_table_count"]) == (5, 1)
    assert [(item["database_name"], [schema["schema_name"] for schema in item["schemas"]])
            for item in summary["databases"]] == [("Other", ["sales"]), ("Warehouse", ["public"])]
    tables = {table["table_name"]: table for table in summary["databases"][1]["schemas"][0]["tables"]}
    assert list(tables) == ["customers", "metric_catalog", "metric_values", "orders"]
    assert tables["orders"] == {
        "dataset_id": 1, "table_name": "orders", "dataset_kind": "physical", "is_saved": True,
        "display_name": "Đơn hàng", "layout": "wide", "column_count": 6, "described_column_count": 2,
    }
    assert (tables["customers"]["is_saved"], tables["customers"]["described_column_count"]) == (False, 1)


def test_summary_leaves_out_datasets_the_caller_cannot_read(env, warehouse):
    env.catalog.denied.add(2)
    env.catalog.hidden.add(5)

    summary = call_route(env.app, API.get_summary).json

    names = [
        table["table_name"]
        for item in summary["databases"] for schema in item["schemas"] for table in schema["tables"]
    ]
    assert names == ["metric_catalog", "metric_values", "orders"]


def test_stats(env, warehouse):
    put_table(env, warehouse["orders"], display_name="Đơn hàng")
    put_columns(env, warehouse["orders"], [
        {"column_name": "id", "display_name": "Mã đơn"},
        {"column_name": "customer_id", "display_name": "Khách", "referenced_column": reference(2, "id")},
    ])
    put_columns(env, warehouse["values"], [
        {"column_name": "metric_id", "display_name": "Chỉ số", "referenced_column": reference(4, "metric_id")},
    ])
    put_columns(env, warehouse["catalog"], [
        {"column_name": "code", "display_name": "Mã", "referenced_column": reference(4, "metric_id")},
    ])

    response = call_route(env.app, API.get_stats, query={"limit": 2})

    assert response.status == 200
    stats = response.json
    counts = ("table_count", "described_table_count", "column_count", "described_column_count")
    assert [stats[name] for name in counts] == [5, 1, 14, 4]
    assert [(item["database_name"], item["schema_name"], item["table_count"], item["described_table_count"])
            for item in stats["schemas"]] == [("Other", "sales", 1, 0), ("Warehouse", "public", 4, 1)]
    assert [(item["table_name"], item["column_count"], item["described_column_count"])
            for item in stats["most_columns"]] == [("orders", 6, 2), ("metric_catalog", 4, 1)]
    assert stats["most_columns"][0]["display_name"] == "Đơn hàng"
    assert [(item["table_name"], item["referencing_table_count"]) for item in stats["most_referenced"]] == [
        ("customers", 1), ("metric_catalog", 1),
    ]
    assert call_route(env.app, API.get_stats, query={"limit": 0}).status == 422
    assert call_route(env.app, API.get_stats, query={"limit": "x"}).json["code"] == "invalid_query_parameter"


def test_a_column_superset_dropped_is_hidden_and_comes_back_with_its_name(env, warehouse):
    orders = warehouse["orders"]
    put_table(env, orders, column_roles=[{"role": "time", "column_name": "order_date"}])
    put_columns(env, orders, [
        {"column_name": "order_date", "display_name": "Ngày đặt", "synonyms": ["ngày"]},
        {"column_name": "customer_id", "display_name": "Khách", "referenced_column": reference(2, "id")},
    ])
    order_date = orders.columns.pop(3)
    warehouse["customers"].columns.clear()

    body = get_dictionary(env, 1).json
    assert body["column_roles"] == []
    customer = next(item for item in body["columns"] if item["column_name"] == "customer_id")
    assert (customer["is_saved"], customer["referenced_column"]) == (True, None)

    # Superset recreated the column row when the dataset was synced; the dictionary follows the name.
    orders.columns.insert(3, column(order_date.column_name, "DATE", is_dttm=True))
    body = get_dictionary(env, 1).json
    assert body["column_roles"] == [{"role": "time", "qualifier": None, "column_name": "order_date"}]
    restored = next(item for item in body["columns"] if item["column_name"] == "order_date")
    assert (restored["display_name"], restored["synonyms"]) == ("Ngày đặt", ["ngày"])


def test_a_viewer_reads_but_cannot_edit(env, warehouse):
    env.sign_in(env.add_user(2, "viewer", VIEWER))

    response = get_dictionary(env, 1)
    assert (response.status, response.json["can_edit"]) == (200, False)
    assert call_route(env.app, API.get_summary).status == 200
    denied = put_table(env, warehouse["orders"])
    assert (denied.status, denied.json["code"]) == (403, "edit_permission_required")
    autofill = call_route(env.app, API.autofill_dataset_dictionary, "POST", dataset_id=1)
    assert autofill.status == 403


def test_an_editor_edits_only_datasets_superset_lets_them_read(env, warehouse):
    env.sign_in(env.add_user(2, "editor", EDITOR))
    env.catalog.denied.add(2)

    assert get_dictionary(env, 1).json["can_edit"] is True
    assert put_table(env, warehouse["orders"]).status == 200
    denied = put_table(env, warehouse["customers"])
    assert (denied.status, denied.json["code"]) == (403, "dataset_access_required")
    assert get_dictionary(env, 2).json["code"] == "dataset_access_required"


@pytest.mark.parametrize("roles", [(), (QUERY,)])
def test_reading_needs_the_view_permission(env, warehouse, roles):
    env.sign_in(env.add_user(2, "someone", *roles))

    for response in (get_dictionary(env, 1), call_route(env.app, API.get_summary), call_route(env.app, API.get_stats)):
        assert (response.status, response.json["code"]) == (403, "view_permission_required")


def test_a_write_needs_a_valid_csrf_token(env, warehouse, monkeypatch):
    from wtforms import ValidationError

    from text_to_bi.superset_text_to_bi.core import security

    def reject(token):
        raise ValidationError("bad token")

    monkeypatch.setattr(security, "validate_csrf", reject)

    response = put_table(env, warehouse["orders"])
    assert (response.status, response.json["code"]) == (403, "csrf_token_invalid")


def test_an_unexpected_error_rolls_back_and_answers_a_safe_500(env, warehouse, monkeypatch):
    from text_to_bi.superset_text_to_bi.modules.data_dictionary.services import dictionary_service

    def broken(*args, **kwargs):
        raise RuntimeError("database exploded at SELECT secret")

    put_table(env, warehouse["orders"], display_name="Đơn hàng")
    monkeypatch.setattr(dictionary_service.DataDictionaryService, "_describe", broken)

    response = put_table(env, warehouse["orders"], display_name="Đổi tên")

    assert (response.status, response.json) == (500, {"code": "internal_error", "message": "Đã xảy ra lỗi hệ thống."})
    assert env.session.scalar(select(TableDictionary)).display_name == "Đơn hàng"
