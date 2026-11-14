from types import SimpleNamespace

import pytest

from text_to_bi.superset_semantic_layer.modules.metric_management.exceptions import (
    MetricContractValidationError,
    MetricSelfApprovalError,
)
from text_to_bi.superset_semantic_layer.modules.metric_management.services import srv_metric_contract, srv_metric_def, srv_metric_event
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_contract import (
    MetricContractService,
    contract_is_approved_current,
    metric_contract_hash,
    metric_contract_state,
)
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_def import MetricDefService
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_query_defaults import DatasetTimeContext
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_validation import (
    METRIC_CONTRACT_RULE,
    metric_contract_ineligibility,
    metric_is_eligible_for_contract,
    parse_contract_metric,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import connection_identity


def _objects():
    dataset = SimpleNamespace(
        id=7,
        catalog="analytics",
        schema="public",
        table_name="weather_daily",
        sql=None,
        database=SimpleNamespace(id=3, database_name="warehouse", sqlalchemy_uri="postgresql://user:secret@db:5432/warehouse"),
        columns=[SimpleNamespace(column_name="temperature_c", is_active=True, expression=None)],
    )
    metric = SimpleNamespace(id=19, metric_name="average_temperature", expression="AVG(temperature_c)")
    return dataset, metric


def test_metric_contract_hash_binds_dataset_metric_and_live_definition():
    dataset, metric = _objects()
    original = metric_contract_hash(dataset, metric)

    metric.expression = "AVG(temperature_f)"
    assert metric_contract_hash(dataset, metric) != original
    metric.expression = "AVG(temperature_c)"
    dataset.table_name = "weather_monthly"
    assert metric_contract_hash(dataset, metric) != original
    dataset.table_name = "weather_daily"
    dataset.database.id = 4
    assert metric_contract_hash(dataset, metric) != original


def test_hash_never_contains_connection_secret_and_binds_metric_column_expression():
    dataset, metric = _objects()
    assert "secret" not in str(connection_identity(dataset.database))
    original = metric_contract_hash(dataset, metric)
    dataset.columns[0].expression = "temperature_c::numeric"
    assert metric_contract_hash(dataset, metric) != original


@pytest.mark.parametrize("expression", ["SUM(temperature_c + 1)", "SUM((SELECT secret FROM users))"])
def test_contract_rejects_unsafe_metric_expressions(expression):
    dataset, metric = _objects()
    metric.expression = expression
    assert not metric_is_eligible_for_contract(dataset, metric)


def _weather_objects(expression):
    dataset, metric = _objects()
    dataset.columns = [
        SimpleNamespace(column_name=name, is_active=True, expression=None)
        for name in ("loai_quan_sat", "nhiet_do_c", "tong_luong_mua_mm")
    ]
    metric.expression = expression
    return dataset, metric


@pytest.mark.parametrize(
    "expression",
    [
        "AVG(CASE WHEN loai_quan_sat = 'DU_BAO_GIO' THEN nhiet_do_c END)",
        "SUM(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' THEN tong_luong_mua_mm END)",
        "COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0 THEN 1 END)",
        "MAX(CASE WHEN loai_quan_sat IN ('A', 'B') AND NOT nhiet_do_c IS NULL THEN nhiet_do_c ELSE NULL END)",
        'MIN("nhiet_do_c")',
    ],
)
def test_contract_accepts_conditional_aggregates_over_dataset_columns(expression):
    assert metric_is_eligible_for_contract(*_weather_objects(expression))


@pytest.mark.parametrize(
    "expression",
    [
        "AVG(CASE WHEN loai_quan_sat = 'A' THEN nhiet_do_c WHEN loai_quan_sat = 'B' THEN tong_luong_mua_mm END)",
        "AVG(CASE WHEN loai_quan_sat = 'A' THEN nhiet_do_c ELSE tong_luong_mua_mm END)",
        "AVG(CASE WHEN LOWER(loai_quan_sat) = 'a' THEN nhiet_do_c END)",
        "AVG(CASE WHEN loai_quan_sat IN (SELECT secret FROM users) THEN nhiet_do_c END)",
        "AVG(CASE WHEN users.role = 'admin' THEN nhiet_do_c END)",
        "AVG(CASE WHEN unknown_column = 'A' THEN nhiet_do_c END)",
        "AVG(DISTINCT nhiet_do_c)",
        "SUM(nhiet_do_c) FILTER (WHERE loai_quan_sat = 'A')",
        "MAX(SUM(nhiet_do_c))",
        "COUNT(*)",
        "COUNT(1)",
        "AVG(nhiet_do_c) OVER (PARTITION BY loai_quan_sat)",
        "{{ metric }}",
    ],
)
def test_contract_rejects_metrics_outside_the_conditional_aggregate_shape(expression):
    assert not metric_is_eligible_for_contract(*_weather_objects(expression))


def test_contract_rejects_a_condition_column_that_is_calculated_or_inactive():
    dataset, metric = _weather_objects("AVG(CASE WHEN loai_quan_sat = 'DU_BAO_GIO' THEN nhiet_do_c END)")
    dataset.columns[0].expression = "UPPER(raw_type)"
    assert not metric_is_eligible_for_contract(dataset, metric)
    dataset.columns[0].expression = None
    dataset.columns[0].is_active = False
    assert not metric_is_eligible_for_contract(dataset, metric)


def test_parse_contract_metric_separates_aggregation_measure_and_condition():
    expression = "COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0 THEN 1 END)"
    assert parse_contract_metric(expression).as_dict() == {
        "aggregation": "COUNT",
        "measure_column": None,
        "measure_constant": "1",
        "condition": "loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0",
        "denominator": None,
        "scale": None,
        "columns": ["loai_quan_sat", "tong_luong_mua_mm"],
    }
    assert parse_contract_metric("AVG(nhiet_do_c)").as_dict()["condition"] is None
    assert parse_contract_metric("SUM(a) / COUNT(b)") is None


def test_parse_contract_metric_reads_a_ratio_of_two_contract_aggregates():
    expression = (
        "100.0 * COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0 THEN 1 END)"
        " / NULLIF(COUNT(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' THEN 1 END), 0)"
    )
    formula = parse_contract_metric(expression).as_dict()
    assert formula["aggregation"] == "COUNT" and formula["scale"] == "100.0"
    assert formula["condition"] == "loai_quan_sat = 'DU_BAO_NGAY' AND tong_luong_mua_mm > 0"
    assert formula["denominator"] == {
        "aggregation": "COUNT",
        "measure_column": None,
        "measure_constant": "1",
        "condition": "loai_quan_sat = 'DU_BAO_NGAY'",
    }
    assert parse_contract_metric("SUM(a) * 1.0 / NULLIF(SUM(b), 0)").as_dict()["scale"] == "1.0"
    parenthesized = parse_contract_metric("(100.0 * SUM(a)) / NULLIF(SUM(b), 0.0)")
    assert parenthesized.as_dict()["denominator"]["measure_column"] == "b"


@pytest.mark.parametrize(
    "expression",
    [
        "100 * COUNT(a) / NULLIF(COUNT(b), 0)",
        "100.0 * COUNT(a) / COUNT(b)",
        "COUNT(a) / NULLIF(COUNT(b), 0) * 100.0",
        "-1.0 * SUM(a) / NULLIF(SUM(b), 0)",
        "100.0 * SUM(a) / NULLIF(SUM(b), 1)",
        "100.0 * SUM(a / b) / NULLIF(SUM(c), 0)",
        "100.0 * SUM(CASE WHEN a / b > 1 THEN 1 END) / NULLIF(SUM(c), 0)",
        "100.0 * SUM(SUM(a)) / NULLIF(SUM(b), 0)",
        "100.0 * SUM(t.a) / NULLIF(SUM(b), 0)",
    ],
)
def test_a_ratio_needs_a_decimal_scale_a_guarded_denominator_and_contract_terms(expression):
    assert parse_contract_metric(expression) is None


def test_a_ratio_names_a_missing_denominator_column():
    expression = "100.0 * COUNT(CASE WHEN loai_quan_sat = 'A' THEN 1 END) / NULLIF(COUNT(missing), 0)"
    dataset, metric = _weather_objects(expression)
    assert metric_contract_ineligibility(dataset, metric) == "Cột missing không có trong dataset."


def test_the_hash_of_a_plain_metric_stays_the_same_so_existing_approvals_stay_current():
    assert metric_contract_hash(*_objects()) == "dfeacb9e15b6bc5524ed83dabc77d9e7ef416dddf622e12cb5af46195f773928"


def test_ineligibility_names_the_offending_column_or_dataset():
    dataset, metric = _weather_objects("AVG(CASE WHEN missing = 'A' THEN nhiet_do_c END)")
    assert metric_contract_ineligibility(dataset, metric) == "Cột missing không có trong dataset."
    metric.expression = "AVG(CASE WHEN loai_quan_sat = 'A' THEN nhiet_do_c END)"
    dataset.columns[0].expression = "UPPER(raw_type)"
    assert metric_contract_ineligibility(dataset, metric) == "Cột loai_quan_sat là cột tính toán."
    dataset.columns[0].expression = None
    assert metric_contract_ineligibility(dataset, metric) is None
    metric.expression = "SUM(a) / COUNT(b)"
    assert metric_contract_ineligibility(dataset, metric) == METRIC_CONTRACT_RULE


def test_metric_contract_state_covers_every_review_stage():
    dataset, metric = _objects()
    assert metric_contract_state(None, dataset, metric) == "not_started"
    expression_hash = metric_contract_hash(dataset, metric)
    contract = SimpleNamespace(
        dataset_id=dataset.id, metric_id=metric.id, status="draft", expression_hash=expression_hash
    )
    assert metric_contract_state(contract, dataset, metric) == "draft"
    contract.status = "approved"
    assert metric_contract_state(contract, dataset, metric) == "approved"
    metric.expression = "SUM(temperature_c)"
    assert metric_contract_state(contract, dataset, metric) == "outdated"
    contract.status = "draft"
    assert metric_contract_state(contract, dataset, metric) == "outdated"
    contract.status = "revoked"
    assert metric_contract_state(contract, dataset, metric) == "revoked"
    metric.expression = "SUM(temperature_c) / 2"
    assert metric_contract_state(None, dataset, metric) == "ineligible"


def test_a_virtual_dataset_is_eligible_but_editing_its_sql_voids_the_approval():
    dataset, metric = _objects()
    dataset.sql = "SELECT city, temperature_c FROM weather_daily"
    assert metric_is_eligible_for_contract(dataset, metric)
    approved_hash = metric_contract_hash(dataset, metric)
    dataset.sql = "SELECT city, temperature_c FROM weather_daily WHERE city = 'Hue'"
    assert metric_contract_hash(dataset, metric) != approved_hash


def test_contract_rejects_computed_metric_column():
    dataset, metric = _objects()
    dataset.columns[0].expression = "temperature_c + 1"
    assert not metric_is_eligible_for_contract(dataset, metric)


def test_only_an_approved_current_contract_is_executable():
    dataset, metric = _objects()
    contract = SimpleNamespace(
        dataset_id=dataset.id,
        metric_id=metric.id,
        status="approved",
        expression_hash=metric_contract_hash(dataset, metric),
    )

    assert contract_is_approved_current(contract, dataset, metric)
    contract.status = "candidate"
    assert not contract_is_approved_current(contract, dataset, metric)
    contract.status = "revoked"
    assert not contract_is_approved_current(contract, dataset, metric)
    contract.status = "approved"
    metric.metric_name = "changed_name"
    assert not contract_is_approved_current(contract, dataset, metric)
    metric.metric_name = "average_temperature"
    contract.dataset_id = 99
    assert not contract_is_approved_current(contract, dataset, metric)


def _metric_contract_service(monkeypatch):
    dataset, metric = _objects()
    definition = SimpleNamespace(
        id=31,
        dataset_id=dataset.id,
        metric_id=metric.id,
        business_definition="Average temperature.",
        unit="C",
        steward_id=None,
        grain=None,
        row_kind_value=None,
        time_column=None,
        time_window=None,
        time_anchor=None,
        default_filters=None,
    )
    repository_state = SimpleNamespace(contract=None, events=[])

    class ContractRepository:
        def read_by_metric(self, metric_id):
            contract = repository_state.contract
            return contract if contract is not None and contract.metric_id == metric_id else None

        def create(self, values):
            repository_state.contract = SimpleNamespace(
                id=41,
                dataset_id=definition.dataset_id,
                metric_id=definition.metric_id,
                definition=definition,
                **values,
            )
            return repository_state.contract

        def update(self, contract, values):
            vars(contract).update(values)
            return contract

    class DefinitionRepository:
        def read_by_metric(self, metric_id):
            return definition if metric_id == definition.metric_id else None

        def update(self, item, values):
            vars(item).update(values)
            return item

    class EventRepository:
        def create(self, values, flush=False):
            event = SimpleNamespace(id=len(repository_state.events) + 1, **values)
            repository_state.events.append(event)
            return event

    contract_repository = ContractRepository()
    definition_repository = DefinitionRepository()
    user = SimpleNamespace(id=3)
    repository_state.contract_repository = contract_repository
    repository_state.definition_repository = definition_repository
    monkeypatch.setattr(srv_metric_contract, "metric_contract_repository", lambda: contract_repository)
    monkeypatch.setattr(srv_metric_contract, "metric_definition_repository", lambda: definition_repository)
    monkeypatch.setattr(srv_metric_contract, "query_defaults_for", lambda *_: None)
    monkeypatch.setattr(srv_metric_contract.MetricContractService, "_ineligibility", staticmethod(lambda *_: None))
    monkeypatch.setattr(srv_metric_contract, "current_user", user)
    monkeypatch.setattr(srv_metric_def, "metric_contract_repository", lambda: contract_repository)
    monkeypatch.setattr(srv_metric_def, "metric_definition_repository", lambda: definition_repository)
    monkeypatch.setattr(srv_metric_event, "metric_contract_event_repository", lambda: EventRepository())
    monkeypatch.setattr(srv_metric_event, "current_user", user)
    return dataset, metric, definition, repository_state, user, MetricContractService()


def test_metric_service_requires_second_reviewer_and_records_both_actors(monkeypatch):
    dataset, metric, _, state, user, service = _metric_contract_service(monkeypatch)
    monkeypatch.setattr(srv_metric_contract, "second_reviewer_required", lambda: True)

    contract = service.propose(dataset, metric, {"reason": "Ready for review."})
    assert contract.status == "draft" and contract.owner_id == 3
    with pytest.raises(MetricSelfApprovalError):
        service.approve(dataset, metric, {})

    user.id = 5
    assert service.approve(dataset, metric, {"reason": "Checked."}).status == "approved"
    assert [(event.action, event.actor_id) for event in state.events] == [("candidate", 3), ("approve", 5)]


def test_metric_service_reproposal_changes_owner_and_revoke_requires_reason(monkeypatch):
    dataset, metric, _, state, user, service = _metric_contract_service(monkeypatch)
    monkeypatch.setattr(srv_metric_contract, "second_reviewer_required", lambda: False)

    contract = service.propose(dataset, metric, {})
    user.id = 8
    assert service.propose(dataset, metric, {}).owner_id == 8
    assert [event.action for event in state.events] == ["candidate", "candidate"]
    with pytest.raises(MetricContractValidationError):
        service.revoke(dataset, metric, {})
    assert contract.status == "draft"

    assert service.revoke(dataset, metric, {"reason": "Formula was wrong."}).status == "revoked"
    with pytest.raises(MetricContractValidationError):
        service.revoke(dataset, metric, {"reason": "Duplicate revoke."})
    assert [event.action for event in state.events] == ["candidate", "candidate", "revoke"]


def test_metric_service_requires_a_business_definition_before_proposal(monkeypatch):
    dataset, metric, _, state, _, service = _metric_contract_service(monkeypatch)
    state.definition_repository.read_by_metric = lambda _metric_id: None

    with pytest.raises(MetricContractValidationError):
        service.propose(dataset, metric, {})
    assert state.contract is None and state.events == []


@pytest.mark.parametrize(
    "body",
    [None, {}, {"business_definition": "   "}, {"business_definition": "meaning", "unit": 17}],
)
def test_metric_definition_service_rejects_invalid_business_fields(body):
    with pytest.raises(MetricContractValidationError):
        MetricDefService._checked_definition(body)


def test_metric_definition_and_query_defaults_updates_persist_and_create_audit_events(monkeypatch):
    dataset, metric, definition, state, _, _ = _metric_contract_service(monkeypatch)
    service = MetricDefService()

    saved = service.update(dataset, metric, {"business_definition": "  Average temperature.  ", "unit": " C "})
    assert saved is definition and saved.business_definition == "Average temperature." and saved.unit == "C"
    assert state.events[-1].action == "definition"

    dataset.columns = [
        SimpleNamespace(column_name="date", is_active=True, expression=None, type="DATE", groupby=True, filterable=True),
        SimpleNamespace(column_name="temperature_c", is_active=True, expression=None, type="FLOAT", groupby=True, filterable=True),
    ]
    time_context = DatasetTimeContext("date", None, {None: "day"}, {"date"})
    monkeypatch.setattr(srv_metric_def, "dataset_time_context", lambda _: time_context)
    defaults = service.update_query_defaults(
        dataset,
        metric,
        {
            "grain": "week",
            "time_column": "date",
            "time_window": "last_7_day",
            "time_anchor": "latest_data",
            "default_filters": [{"column": "temperature_c", "operator": ">", "value": 0}],
        },
    )
    assert defaults.grain == "week" and defaults.time_anchor == "latest_data"
    assert definition.grain == "week" and definition.time_column == "date"
    assert state.events[-1].action == "definition" and "grain" in state.events[-1].reason
