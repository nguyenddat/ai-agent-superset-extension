from types import SimpleNamespace

import pytest
from support import call_route, column, database, dataset, parse_events

from text_to_bi.superset_text_to_bi.modules.data_dictionary.routes import route_data_dictionary
from text_to_bi.superset_text_to_bi.modules.data_dictionary.routes.route_data_dictionary import DataDictionaryAPI
from text_to_bi.superset_text_to_bi.modules.data_dictionary.services import (
    DataDictionaryAutofillService,
    autofill_lock,
    dictionary_suggester,
)
from text_to_bi.superset_text_to_bi.modules.data_dictionary.services.dictionary_suggester import (
    ColumnSuggestion,
    ColumnSuggestions,
    LlmDictionarySuggester,
    TableSuggestion,
)

API = DataDictionaryAPI


class ProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider error {status_code}")
        self.status_code = status_code


class FakeSuggester:
    def __init__(self, columns=None, table=None):
        self.columns = columns or {}
        self.table = table
        self.ready = True
        self.column_error = None
        self.order = None
        self.contexts = []
        self.table_context = None

    def ensure_ready(self):
        if not self.ready:
            raise RuntimeError("missing key")

    def suggest_column_batches(self, contexts):
        self.contexts = contexts
        for index in self.order or range(len(contexts)):
            if self.column_error:
                yield index, self.column_error
                continue
            yield index, ColumnSuggestions(suggestions=[
                ColumnSuggestion(column_name=item["column_name"], **self.columns[item["column_name"]])
                for item in contexts[index]["columns"] if item["column_name"] in self.columns
            ])

    def suggest_table(self, context):
        self.table_context = context
        return self.table


@pytest.fixture
def orders(env):
    source = database(1, "Warehouse")
    orders = dataset(1, "orders", [
        column("id", "BIGINT"), column("amount", "NUMERIC"), column("status", "VARCHAR(20)"),
        column("created_at", "TIMESTAMP", is_dttm=True),
    ], source)
    env.add_datasets(orders, dataset(2, "empty", [], source))
    return orders


@pytest.fixture
def suggester(env, monkeypatch):
    fake = FakeSuggester(
        columns={
            "id": {"display_name": "Mã đơn hàng"},
            "amount": {"display_name": "Giá trị đơn", "unit": "VND", "business_term": "Doanh thu"},
            "status": {"display_name": "Trạng thái", "description": "Trạng thái xử lý đơn"},
            "created_at": {"display_name": "Thời điểm tạo"},
        },
        table=TableSuggestion(
            display_name="Đơn hàng", description="Các đơn hàng đã đặt", grain_description="Một đơn hàng",
            created_at_column="created_at",
        ),
    )
    monkeypatch.setattr(
        route_data_dictionary, "data_dictionary_autofill_service",
        lambda: DataDictionaryAutofillService(env.session, fake),
    )
    return fake


def autofill(env, dataset_id=1):
    return call_route(env.app, API.autofill_dataset_dictionary, "POST", dataset_id=dataset_id)


def dictionary(env):
    return call_route(env.app, API.get_dataset_dictionary, dataset_id=1).json


def test_streams_and_saves_suggestions_for_an_unsaved_dataset(env, orders, suggester):
    events = parse_events(autofill(env))

    assert [name for name, _ in events] == ["status", "columns", "status", "table", "done"]
    assert events[1][1]["processed"] == 4
    assert {item["column_name"]: item["display_name"] for item in events[1][1]["columns"]} == {
        "id": "Mã đơn hàng", "amount": "Giá trị đơn", "status": "Trạng thái", "created_at": "Thời điểm tạo",
    }
    assert events[3][1]["can_edit"] is True
    assert events[-1][1] == {"processed": 4, "total": 4, "failed_columns": 0, "table_filled": True}
    assert suggester.table_context["columns"][2]["description"] == "Trạng thái xử lý đơn"

    saved = dictionary(env)
    assert (saved["is_saved"], saved["display_name"], saved["grain_description"]) == (True, "Đơn hàng", "Một đơn hàng")
    assert [(role["role"], role["column_name"]) for role in saved["column_roles"]] == [("created_at", "created_at")]
    columns = {item["column_name"]: item for item in saved["columns"]}
    assert all(item["is_saved"] for item in columns.values())
    assert (columns["amount"]["unit"], columns["amount"]["business_term"], columns["amount"]["semantic_role"]) == (
        "VND", "Doanh thu", "measure",
    )
    assert (columns["created_at"]["temporal_kind"], columns["created_at"]["semantic_role"]) == ("timestamp", "time")
    assert columns["id"]["semantic_role"] == "key"


def test_keeps_values_the_user_already_wrote(env, orders, suggester):
    call_route(env.app, API.save_table_dictionary, "PUT", {
        "display_name": "Đơn bán", "description": "Mô tả của người dùng",
    }, dataset_id=1)
    call_route(env.app, API.save_column_dictionaries, "PUT", {"columns": [
        {"column_name": "amount", "display_name": "Tổng tiền", "unit": "USD"},
    ]}, dataset_id=1)

    autofill(env)

    saved = dictionary(env)
    assert (saved["display_name"], saved["description"], saved["grain_description"]) == (
        "Đơn bán", "Mô tả của người dùng", "Một đơn hàng",
    )
    amount = next(item for item in saved["columns"] if item["column_name"] == "amount")
    assert (amount["display_name"], amount["unit"], amount["business_term"]) == ("Tổng tiền", "USD", "Doanh thu")


def test_what_superset_already_says_wins_over_the_model_on_a_new_entry(env, orders, suggester):
    orders.columns[2].verbose_name = "Tình trạng"
    orders.columns[2].description = "Mô tả trong Superset"

    autofill(env)

    status = next(item for item in dictionary(env)["columns"] if item["column_name"] == "status")
    assert (status["display_name"], status["description"]) == ("Tình trạng", "Mô tả trong Superset")


def test_ignores_unknown_columns_and_reports_missing_ones(env, orders, suggester):
    suggester.columns = {"status": {"display_name": "Trạng thái"}, "ghost": {"display_name": "Ma"}}
    suggester.table = None

    events = parse_events(autofill(env))

    assert (events[-1][1]["failed_columns"], events[-1][1]["table_filled"]) == (3, False)
    saved = dictionary(env)
    assert saved["is_saved"] is False
    assert [item["column_name"] for item in saved["columns"] if item["is_saved"]] == ["status"]


def test_batches_of_eight_are_saved_and_reported_as_each_one_finishes(env, suggester):
    names = [f"metric_{index:02d}" for index in range(20)]
    env.add_datasets(dataset(3, "wide", [column(name, "NUMERIC") for name in names], database(1, "Warehouse")))
    suggester.columns = {name: {"display_name": f"Chỉ số {name[-2:]}"} for name in names}
    suggester.order = [2, 0, 1]

    events = parse_events(autofill(env, 3))

    assert [len(context["columns"]) for context in suggester.contexts] == [8, 8, 4]
    assert all(context["table_name"] == "wide" for context in suggester.contexts)
    batches = [data for name, data in events if name == "columns"]
    assert [(len(data["columns"]), data["processed"]) for data in batches] == [(4, 4), (8, 12), (8, 20)]
    assert [item["column_name"] for item in batches[0]["columns"]] == names[16:]
    assert events[-1] == ("done", {"processed": 20, "total": 20, "failed_columns": 0, "table_filled": True})


def test_a_failed_batch_is_skipped_and_the_others_stay_saved(env, orders, suggester, monkeypatch):
    original = DataDictionaryAutofillService._suggest_table

    def broken_table(self, plan, suggestions):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(DataDictionaryAutofillService, "_suggest_table", broken_table)
    events = parse_events(autofill(env))

    assert [name for name, _ in events] == ["status", "columns", "status", "error"]
    assert events[-1][1] == {"code": "dictionary_autofill_failed", "message": "Không thể tạo gợi ý từ điển dữ liệu."}
    assert all(item["is_saved"] for item in dictionary(env)["columns"])
    monkeypatch.setattr(DataDictionaryAutofillService, "_suggest_table", original)
    assert parse_events(autofill(env))[-1][0] == "done"


def test_rejected_api_key_ends_the_stream_with_an_error(env, orders, suggester):
    suggester.column_error = ProviderError(401)

    events = parse_events(autofill(env))

    assert events[-1] == ("error", {
        "code": "dictionary_autofill_unavailable", "message": "Nhà cung cấp mô hình từ chối API key.",
    })
    assert dictionary(env)["is_saved"] is False
    suggester.column_error = None
    assert parse_events(autofill(env))[-1][0] == "done"


def test_nothing_suggested_is_an_error(env, orders, suggester):
    suggester.column_error = ProviderError(500)
    suggester.table = None

    assert parse_events(autofill(env))[-1] == ("error", {
        "code": "dictionary_autofill_failed", "message": "Mô hình không trả về gợi ý hợp lệ; thử lại sau.",
    })


def test_rejects_requests_before_streaming(env, orders, suggester):
    assert autofill(env, 2).status == 422
    lease = autofill_lock.claim_autofill(env.engine, 1)
    in_progress = autofill(env)
    assert (in_progress.status, in_progress.json["code"]) == (409, "dictionary_autofill_in_progress")
    lease.release()
    suggester.ready = False
    unavailable = autofill(env)
    assert unavailable.status == 503
    assert "OPENROUTER_API_KEY" in unavailable.json["message"]
    assert autofill(env, 99).status == 404


def test_the_lock_is_released_when_the_stream_ends_or_the_client_leaves(env, orders, suggester):
    parse_events(autofill(env))
    assert 1 not in autofill_lock._local_running

    with env.app.test_request_context(method="POST"):
        response = API.autofill_dataset_dictionary.__wrapped__.__wrapped__(SimpleNamespace(), dataset_id=1)
        assert 1 in autofill_lock._local_running
        response.close()
    assert 1 not in autofill_lock._local_running


def test_the_model_suggester_runs_at_most_four_batches_at_once(monkeypatch):
    calls = {}

    class FakeModel:
        def batch_as_completed(self, inputs, config, return_exceptions):
            calls.update(inputs=inputs, config=config, return_exceptions=return_exceptions)
            yield 1, {"suggestions": [{"column_name": "b", "display_name": "B"}]}
            yield 0, RuntimeError("timeout")

    monkeypatch.setattr(dictionary_suggester, "structured_model", lambda schema: FakeModel())
    contexts = [{"columns": [{"column_name": "a"}]}, {"columns": [{"column_name": "b"}]}]

    results = list(LlmDictionarySuggester().suggest_column_batches(contexts))

    assert (calls["config"], calls["return_exceptions"], len(calls["inputs"])) == ({"max_concurrency": 4}, True, 2)
    assert results[0][0] == 1 and results[0][1].suggestions[0].display_name == "B"
    assert results[1][0] == 0 and isinstance(results[1][1], RuntimeError)


class FakeLockConnection:
    def __init__(self, acquired):
        self.acquired = acquired
        self.statements = []
        self.closed = self.invalidated = False

    def execution_options(self, **options):
        self.options = options
        return self

    def execute(self, statement, parameters):
        self.statements.append((str(statement), parameters))
        return SimpleNamespace(scalar=lambda: self.acquired)

    def close(self):
        self.closed = True

    def invalidate(self):
        self.invalidated = True


def test_postgres_holds_an_advisory_lock_per_dataset_across_workers():
    connections = [FakeLockConnection(True), FakeLockConnection(False)]
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: connections.pop(0))

    lease = autofill_lock.claim_autofill(engine, 7)
    held = lease.connection
    assert autofill_lock.claim_autofill(engine, 7) is None
    lease.release()
    lease.release()

    assert held.options == {"isolation_level": "AUTOCOMMIT"}
    assert [statement for statement, _ in held.statements] == [
        "SELECT pg_try_advisory_lock(:namespace, :dataset_id)", "SELECT pg_advisory_unlock(:namespace, :dataset_id)",
    ]
    assert held.statements[0][1] == {"namespace": autofill_lock.AUTOFILL_LOCK_NAMESPACE, "dataset_id": 7}
    assert held.closed and not held.invalidated
