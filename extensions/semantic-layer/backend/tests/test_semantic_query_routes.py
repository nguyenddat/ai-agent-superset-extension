from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from wtforms import ValidationError

from text_to_bi.superset_semantic_layer.core.exceptions import (
    AdminRequiredError,
    DatasetAccessError,
    SemanticLayerQueryRequiredError,
    SemanticLayerViewRequiredError,
)
from text_to_bi.superset_semantic_layer.modules.data_dictionary.exceptions import RelationshipValidationError
from text_to_bi.superset_semantic_layer.modules.data_dictionary.routes import route_relationship
from text_to_bi.superset_semantic_layer.modules.metric_management.exceptions import MetricContractValidationError
from text_to_bi.superset_semantic_layer.modules.metric_management.routes import route_crud_metric_def, route_metric_contract


class _Session:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        self.flushes += 1


class _RouteAPI(
    route_metric_contract.MetricContractRoutes,
    route_crud_metric_def.MetricDefinitionRoutes,
    route_relationship.RelationshipRoutes,
):
    def response(self, status, **payload):
        return status, payload

    def response_500(self, **payload):
        return self.response(500, **payload)


def _invoke_route(api, route_name, *arguments, csrf_valid=True, **keywords):
    """Skip FAB's permission/login wrappers while retaining CSRF, transaction, error, and resolver wrappers."""
    handler = getattr(type(api), route_name)
    handler = handler.__wrapped__.__wrapped__
    csrf_globals = handler.__globals__
    prior_request = csrf_globals.get("request")
    prior_validator = csrf_globals.get("validate_csrf")
    csrf_globals["request"] = SimpleNamespace(headers={"X-CSRFToken": "test-token"})
    csrf_globals["validate_csrf"] = lambda _token: None
    if not csrf_valid:
        csrf_globals["validate_csrf"] = lambda _token: (_ for _ in ()).throw(ValidationError())
    try:
        return handler(api, *arguments, **keywords)
    finally:
        csrf_globals["request"] = prior_request
        csrf_globals["validate_csrf"] = prior_validator


def _contract(contract_id=11):
    return SimpleNamespace(
        id=contract_id,
        dataset_id=7,
        metric_id=4,
        status="draft",
        origin="manual",
        owner_id=3,
        approver_id=None,
        approved_at=None,
        revoker_id=None,
        revoked_at=None,
    )


@pytest.fixture
def route_context(monkeypatch):
    import superset

    from text_to_bi.superset_semantic_layer import core

    session = _Session()
    monkeypatch.setattr(superset.db, "session", session)
    monkeypatch.setattr(core.database.db, "session", session)
    dataset = SimpleNamespace(id=7, table_name="weather")
    metric = SimpleNamespace(id=4, metric_name="average_temperature")
    dataset.metrics = [metric]
    user = SimpleNamespace(id=3, roles=[SimpleNamespace(name="Admin")])
    body = {"reason": "Reviewed"}
    access_state = {"dataset_access": True}

    def require_admin():
        if not any(role.name == "Admin" for role in user.roles):
            raise AdminRequiredError()

    def require_query():
        if not any(role.name == "Admin" for role in user.roles):
            raise SemanticLayerQueryRequiredError()

    def require_dataset_access(_dataset):
        if not access_state["dataset_access"]:
            raise DatasetAccessError()

    monkeypatch.setattr(route_metric_contract, "request", SimpleNamespace(get_json=lambda silent=True: body))
    monkeypatch.setattr(route_metric_contract, "current_user", user)
    monkeypatch.setattr(route_metric_contract, "require_admin", require_admin)
    monkeypatch.setattr(route_metric_contract, "require_semantic_layer_query", require_query)
    monkeypatch.setattr(route_metric_contract, "require_dataset_access", require_dataset_access)
    monkeypatch.setattr(route_metric_contract, "ensure_dictionary_tables", lambda: None)
    monkeypatch.setattr(route_metric_contract, "metric_contract_state", lambda *_: "draft")
    from text_to_bi.superset_semantic_layer.modules.metric_management.utils import util_serializer

    monkeypatch.setattr(util_serializer, "user_names", lambda: lambda _user_id: None)
    monkeypatch.setattr(route_crud_metric_def, "request", SimpleNamespace(get_json=lambda silent=True: body))
    monkeypatch.setattr(route_crud_metric_def, "require_admin", require_admin)
    monkeypatch.setattr(route_crud_metric_def, "ensure_dictionary_tables", lambda: None)
    monkeypatch.setattr(route_crud_metric_def, "serialize_metric_definition", lambda definition: definition)
    monkeypatch.setattr(route_relationship, "request", SimpleNamespace(get_json=lambda silent=True: body, args=SimpleNamespace(get=lambda *_args, **_kwargs: None)))
    monkeypatch.setattr(route_relationship, "current_user", user)
    monkeypatch.setattr(route_relationship, "require_admin", require_admin)
    monkeypatch.setattr(route_relationship, "ensure_dictionary_tables", lambda: None)
    from text_to_bi.superset_semantic_layer.modules.superset import dependencies as superset_dependencies

    monkeypatch.setattr(superset_dependencies, "require_dataset", lambda dataset_id: dataset if dataset_id == dataset.id else None)

    return SimpleNamespace(
        api=_RouteAPI(), dataset=dataset, metric=metric, user=user, body=body, session=session,
        access_state=access_state, monkeypatch=monkeypatch
    )


def test_metric_candidate_route_enforces_admin_and_commits_service_result(route_context, monkeypatch):
    context = route_context
    contract = _contract()
    service = Mock()
    service.propose.return_value = contract
    monkeypatch.setattr(route_metric_contract, "MetricContractService", lambda: service)

    context.user.roles = []
    route_arguments = {"dataset_id": context.dataset.id, "metric_id": context.metric.id}
    assert _invoke_route(context.api, "create_metric_contract", **route_arguments)[0] == 403
    service.propose.assert_not_called()
    assert context.session.commits == 0

    context.user.roles = [SimpleNamespace(name="Admin")]
    status, payload = _invoke_route(context.api, "create_metric_contract", **route_arguments)
    assert status == 201 and payload["contract"]["state"] == "draft"
    assert "expression" not in payload["contract"] and "expression_hash" not in payload["contract"]
    service.propose.assert_called_once_with(context.dataset, context.metric, context.body)
    assert context.session.commits == 1


def test_metric_review_routes_delegate_to_service_and_commit_each_transition(route_context, monkeypatch):
    context = route_context
    contract = _contract()
    service = Mock()
    service.approve.return_value = service.revoke.return_value = contract
    monkeypatch.setattr(route_metric_contract, "MetricContractService", lambda: service)

    route_arguments = {"dataset_id": context.dataset.id, "metric_id": context.metric.id}
    approve_status, approved_payload = _invoke_route(context.api, "approve_metric_contract", **route_arguments)
    revoke_status, revoked_payload = _invoke_route(context.api, "revoke_metric_contract", **route_arguments)
    assert approve_status == revoke_status == 200
    assert approved_payload["contract"]["state"] == revoked_payload["contract"]["state"] == "draft"
    service.approve.assert_called_once_with(context.dataset, context.metric, context.body)
    service.revoke.assert_called_once_with(context.dataset, context.metric, context.body)
    assert context.session.commits == 2


def test_metric_candidate_route_rejects_invalid_csrf_before_service(route_context, monkeypatch):
    context = route_context
    service = Mock()
    monkeypatch.setattr(route_metric_contract, "MetricContractService", lambda: service)

    status, payload = _invoke_route(
        context.api,
        "create_metric_contract",
        dataset_id=context.dataset.id,
        metric_id=context.metric.id,
        csrf_valid=False,
    )

    assert status == 403 and "CSRF" in payload["message"]
    service.propose.assert_not_called()
    assert context.session.commits == 0


def test_metric_execute_route_checks_query_and_dataset_access_before_service(route_context, monkeypatch):
    context = route_context
    service = Mock()
    service.execute.return_value = {"error": None, "rows": [{"value": 1}], "preview": False}
    monkeypatch.setattr(route_metric_contract, "MetricExecuteService", lambda: service)
    monkeypatch.setattr(route_metric_contract, "run_chart_query", Mock())
    body = {"dimensions": ["city"]}
    monkeypatch.setattr(route_metric_contract, "request", SimpleNamespace(get_json=lambda silent=True: body))

    context.user.roles = []
    route_arguments = {"dataset_id": context.dataset.id, "metric_id": context.metric.id}
    assert _invoke_route(context.api, "execute_metric_contract", **route_arguments)[0] == 403
    service.execute.assert_not_called()

    context.user.roles = [SimpleNamespace(name="Admin")]
    context.access_state["dataset_access"] = False
    assert _invoke_route(context.api, "execute_metric_contract", **route_arguments)[0] == 403
    service.execute.assert_not_called()

    context.access_state["dataset_access"] = True
    status, payload = _invoke_route(context.api, "execute_metric_contract", **route_arguments)
    assert status == 200 and payload["result"]["rows"] == [{"value": 1}]
    service.execute.assert_called_once_with(context.dataset, context.metric, body, route_metric_contract.run_chart_query)


def test_metric_execute_maps_validation_errors_and_rolls_back(route_context, monkeypatch):
    context = route_context
    service = Mock()
    service.execute.side_effect = MetricContractValidationError("Invalid metric query.")
    monkeypatch.setattr(route_metric_contract, "MetricExecuteService", lambda: service)
    context.user.roles = [SimpleNamespace(name="Admin")]

    assert _invoke_route(
        context.api, "execute_metric_contract", dataset_id=context.dataset.id, metric_id=context.metric.id
    ) == (
        400,
        {"message": "Invalid metric query."},
    )
    assert context.session.rollbacks == 1


def test_metric_definition_update_requires_admin_and_commits(route_context, monkeypatch):
    context = route_context
    definition = {"business_definition": "Average temperature."}
    service = Mock()
    service.update.return_value = definition
    monkeypatch.setattr(route_crud_metric_def, "MetricDefService", lambda: service)
    context.user.roles = []

    route_arguments = {"dataset_id": context.dataset.id, "metric_id": context.metric.id}
    assert _invoke_route(context.api, "update_metric_definition", **route_arguments)[0] == 403
    service.update.assert_not_called()
    assert context.session.commits == 0

    context.user.roles = [SimpleNamespace(name="Admin")]
    assert _invoke_route(context.api, "update_metric_definition", **route_arguments) == (
        200,
        {"definition": definition},
    )
    service.update.assert_called_once_with(context.dataset, context.metric, context.body)
    assert context.session.commits == 1


def test_metric_query_defaults_route_delegates_validation_and_commits(route_context, monkeypatch):
    context = route_context
    defaults_payload = {"grain": "week", "time_column": "date", "default_filters": []}
    defaults = SimpleNamespace(is_empty=lambda: False, as_dict=lambda: defaults_payload)
    service = Mock()
    service.update_query_defaults.return_value = defaults
    monkeypatch.setattr(route_crud_metric_def, "MetricDefService", lambda: service)
    arguments = {"dataset_id": context.dataset.id, "metric_id": context.metric.id}

    status, payload = _invoke_route(context.api, "update_metric_query_defaults", **arguments)

    assert status == 200 and payload["query_defaults"] == defaults_payload
    service.update_query_defaults.assert_called_once_with(context.dataset, context.metric, context.body)
    assert context.session.commits == 1


def test_relationship_candidate_route_delegates_identity_and_commits(route_context, monkeypatch):
    context = route_context
    contract, source, target = object(), object(), object()
    service = Mock()
    service.create_candidate.return_value = (contract, source, target)
    monkeypatch.setattr(route_relationship, "RelationshipService", lambda: service)
    monkeypatch.setattr(route_relationship, "serialize_relationship_contract", lambda *values: values)
    monkeypatch.setattr(route_relationship, "request", SimpleNamespace(get_json=lambda silent=True: {"source": "naming"}))

    status, payload = _invoke_route(context.api, "create_relationship_contract_candidate", context.dataset.id, 22)
    assert status == 201 and payload["contract"] == (contract, source, target)
    service.create_candidate.assert_called_once_with(context.dataset.id, 22, "naming", context.user.id)
    assert context.session.commits == 1


def test_relationship_service_error_returns_domain_status_and_rolls_back(route_context, monkeypatch):
    context = route_context
    service = Mock()
    service.create_candidate.side_effect = RelationshipValidationError("Invalid relationship.")
    monkeypatch.setattr(route_relationship, "RelationshipService", lambda: service)
    monkeypatch.setattr(route_relationship, "request", SimpleNamespace(get_json=lambda silent=True: {}))

    assert _invoke_route(context.api, "create_relationship_contract_candidate", context.dataset.id, 22) == (
        400,
        {"message": "Invalid relationship."},
    )
    assert context.session.rollbacks == 1
    assert context.session.commits == 0


def test_relationship_approve_and_revoke_routes_forward_path_and_contract_identity(route_context, monkeypatch):
    context = route_context
    contract, source, target, entry = object(), object(), object(), object()
    service = Mock()
    service.approve.return_value = (contract, source, target)
    service.revoke.return_value = (contract, entry)
    monkeypatch.setattr(route_relationship, "RelationshipService", lambda: service)
    monkeypatch.setattr(route_relationship, "serialize_relationship_contract", lambda *values: values)
    monkeypatch.setattr(route_relationship, "serialize_revoked_contract", lambda *values: values)
    monkeypatch.setattr(
        route_relationship,
        "request",
        SimpleNamespace(get_json=lambda silent=True: {}, args=SimpleNamespace(get=lambda name, **_: 53 if name == "contract_id" else None)),
    )

    status, payload = _invoke_route(context.api, "approve_relationship_contract", context.dataset.id, 22)
    assert status == 200 and payload["contract"] == (contract, source, target)
    service.approve.assert_called_once_with(context.dataset.id, 22, context.user.id)
    status, payload = _invoke_route(context.api, "revoke_relationship_contract", context.dataset.id, 22)
    assert status == 200 and payload["contract"] == (contract, entry)
    service.revoke.assert_called_once_with(context.dataset.id, 22, 53, context.user.id)
    assert context.session.commits == 2


def test_metric_list_filters_denied_datasets_before_building_entries(route_context, monkeypatch):
    context = route_context
    allowed = context.dataset
    denied = SimpleNamespace(id=8, table_name="private")
    database = SimpleNamespace(id=2)
    entries_service = Mock()
    entries_service.read_entries.return_value = []
    monkeypatch.setattr(route_metric_contract, "require_semantic_layer_view", lambda: None)
    monkeypatch.setattr(route_metric_contract, "datasets_on_database", lambda _: [allowed, denied])
    monkeypatch.setattr(route_metric_contract, "can_access_dataset", lambda dataset: dataset.id == allowed.id)
    monkeypatch.setattr(route_metric_contract, "MetricContractService", lambda: entries_service)
    monkeypatch.setattr(route_metric_contract, "dataset_column_labels", lambda datasets: {allowed.id: {}})
    monkeypatch.setattr(route_metric_contract, "dataset_time_contexts", lambda datasets: {allowed.id: object()})
    monkeypatch.setattr(route_metric_contract, "serialize_query_dataset", lambda dataset, *_: {"id": dataset.id})
    monkeypatch.setattr(route_metric_contract, "serialize_metric_entry", lambda entry: entry)
    monkeypatch.setattr(route_metric_contract, "active_users", list)
    monkeypatch.setattr(route_metric_contract, "serialize_users", lambda users: users)
    monkeypatch.setattr(route_metric_contract, "second_reviewer_required", lambda: True)
    from text_to_bi.superset_semantic_layer.modules.superset import dependencies as superset_dependencies

    monkeypatch.setattr(superset_dependencies, "require_database", lambda database_id: database if database_id == database.id else None)

    monkeypatch.setattr(
        route_metric_contract,
        "require_semantic_layer_view",
        lambda: (_ for _ in ()).throw(SemanticLayerViewRequiredError()),
    )
    assert _invoke_route(context.api, "read_metric_contracts", database_id=database.id)[0] == 403
    entries_service.read_entries.assert_not_called()
    monkeypatch.setattr(route_metric_contract, "require_semantic_layer_view", lambda: None)

    status, payload = _invoke_route(context.api, "read_metric_contracts", database_id=database.id)

    assert status == 200 and payload["datasets"] == [{"id": allowed.id}]
    entries_service.read_entries.assert_called_once_with([allowed])
    assert payload["require_second_reviewer"] is True


def test_metric_contract_read_rejects_dataset_without_access_before_service(route_context, monkeypatch):
    context = route_context
    contract = _contract()
    service = Mock()
    service.read.return_value = contract
    monkeypatch.setattr(route_metric_contract, "require_semantic_layer_view", lambda: None)
    monkeypatch.setattr(route_metric_contract, "MetricContractService", lambda: service)
    monkeypatch.setattr(context.api, "_serialized", lambda *_arguments: {"id": contract.id})
    route_arguments = {"dataset_id": context.dataset.id, "metric_id": context.metric.id}

    context.access_state["dataset_access"] = False
    assert _invoke_route(context.api, "read_metric_contract", **route_arguments)[0] == 403
    service.read.assert_not_called()

    context.access_state["dataset_access"] = True
    assert _invoke_route(context.api, "read_metric_contract", **route_arguments) == (200, {"contract": {"id": contract.id}})
    service.read.assert_called_once_with(context.dataset, context.metric)


def test_metric_event_route_checks_dataset_access_and_preserves_service_history_order(route_context, monkeypatch):
    context = route_context
    events = [SimpleNamespace(action="revoke"), SimpleNamespace(action="approve"), SimpleNamespace(action="candidate")]
    service = Mock()
    service.read_history.return_value = events
    monkeypatch.setattr(route_metric_contract, "require_semantic_layer_view", lambda: None)
    monkeypatch.setattr(route_metric_contract, "MetricEventService", lambda: service)
    monkeypatch.setattr(route_metric_contract, "serialize_metric_events", lambda history: [event.action for event in history])
    route_arguments = {"dataset_id": context.dataset.id, "metric_id": context.metric.id}

    context.access_state["dataset_access"] = False
    assert _invoke_route(context.api, "read_metric_contract_events", **route_arguments)[0] == 403
    service.read_history.assert_not_called()

    context.access_state["dataset_access"] = True
    assert _invoke_route(context.api, "read_metric_contract_events", **route_arguments) == (
        200,
        {"events": ["revoke", "approve", "candidate"]},
    )
    service.read_history.assert_called_once_with(context.metric)


@pytest.mark.parametrize(
    ("state", "origin", "expected_status", "provisional"),
    [
        ("approved", "manual", 200, False),
        ("draft", "ai_agent", 200, True),
        ("draft", "manual", 409, None),
        ("revoked", "ai_agent", 409, None),
    ],
)
def test_agent_metric_route_reuses_or_rejects_existing_contracts(
    route_context, monkeypatch, state, origin, expected_status, provisional
):
    import superset

    monkeypatch.setattr(superset.connectors.sqla.models, "SqlMetric", type("SqlMetric", (), {}), raising=False)
    from text_to_bi.superset_semantic_layer.modules.metric_management.routes import route_metric_candidate

    class AgentRouteAPI(route_metric_candidate.MetricCandidateRoutes):
        def response(self, status, **payload):
            return status, payload

        def response_500(self, **payload):
            return self.response(500, **payload)

    context = route_context
    context.body.update(dataset_id=context.dataset.id, expression="AVG(temperature)")
    metric = context.metric
    contract = SimpleNamespace(origin=origin)
    contracts = Mock()
    contracts.read.return_value = contract
    monkeypatch.setattr(route_metric_candidate, "MetricContractService", lambda: contracts)
    monkeypatch.setattr(route_metric_candidate, "dataset_dictionary_repository", lambda: SimpleNamespace(read=lambda _: SimpleNamespace(dataset_type="aggregate")))
    monkeypatch.setattr(route_metric_candidate, "is_internal_dataset", lambda _: False)
    monkeypatch.setattr(route_metric_candidate, "checked_metric_draft", lambda *_: SimpleNamespace(expression="AVG(temperature)"))
    monkeypatch.setattr(route_metric_candidate, "asked_question", lambda _: "Average temperature?")
    monkeypatch.setattr(route_metric_candidate, "matching_metric", lambda *_: metric)
    monkeypatch.setattr(route_metric_candidate, "metric_contract_state", lambda *_: state)
    monkeypatch.setattr(route_metric_candidate, "request", SimpleNamespace(get_json=lambda silent=True: context.body))
    monkeypatch.setattr(route_metric_candidate, "current_user", context.user)
    monkeypatch.setattr(route_metric_candidate, "require_semantic_layer_query", lambda: None)
    monkeypatch.setattr(route_metric_candidate, "require_dataset_access", lambda _: None)
    monkeypatch.setattr(route_metric_candidate, "ensure_dictionary_tables", lambda: None)
    monkeypatch.setattr(route_metric_candidate, "require_dataset", lambda dataset_id: context.dataset if dataset_id == context.dataset.id else None)
    monkeypatch.setattr(
        route_metric_candidate,
        "metric_definition_repository",
        lambda: SimpleNamespace(read_by_metric=lambda _: SimpleNamespace(business_definition="Average temperature.", unit="C")),
    )
    monkeypatch.setattr(AgentRouteAPI, "_agent_metric", lambda *_: {"metric_id": metric.id})
    context.api = AgentRouteAPI()

    status, payload = _invoke_route(context.api, "create_agent_metric")

    assert status == expected_status
    if provisional is not None:
        assert payload["result"]["provisional"] is provisional
    contracts.propose_for_agent.assert_not_called()


def test_agent_metric_route_appends_flushes_and_proposes_a_unique_metric_name(route_context, monkeypatch):
    import superset

    monkeypatch.setattr(superset.connectors.sqla.models, "SqlMetric", type("SqlMetric", (), {}), raising=False)
    from text_to_bi.superset_semantic_layer.modules.metric_management.routes import route_metric_candidate

    class CandidateRouteAPI(route_metric_candidate.MetricCandidateRoutes):
        def response(self, status, **payload):
            return status, payload

        def response_500(self, **payload):
            return self.response(500, **payload)

    context = route_context
    context.dataset.columns = [SimpleNamespace(column_name="temperature", is_active=True, expression=None)]
    context.body.update(
        dataset_id=context.dataset.id,
        metric_name="average_temperature",
        label="Average temperature",
        expression="MAX(temperature)",
        definition="Maximum temperature.",
        unit="C",
        question="How warm?",
    )
    existing_metric = context.metric
    existing_metric.expression = "AVG(temperature)"
    contracts = Mock()
    contracts.read.return_value = None
    contracts.count_agent_drafts.return_value = 0
    monkeypatch.setattr(route_metric_candidate, "MetricContractService", lambda: contracts)
    monkeypatch.setattr(route_metric_candidate, "request", SimpleNamespace(get_json=lambda silent=True: context.body))
    monkeypatch.setattr(route_metric_candidate, "current_user", context.user)
    monkeypatch.setattr(route_metric_candidate, "require_semantic_layer_query", lambda: None)
    monkeypatch.setattr(route_metric_candidate, "require_dataset_access", lambda _: None)
    monkeypatch.setattr(route_metric_candidate, "ensure_dictionary_tables", lambda: None)
    monkeypatch.setattr(route_metric_candidate, "require_dataset", lambda _: context.dataset)
    monkeypatch.setattr(
        route_metric_candidate,
        "dataset_dictionary_repository",
        lambda: SimpleNamespace(read=lambda _: SimpleNamespace(dataset_type="aggregate")),
    )
    monkeypatch.setattr(route_metric_candidate, "is_internal_dataset", lambda _: False)
    monkeypatch.setattr(
        CandidateRouteAPI, "_agent_metric", lambda _self, dataset, metric: {"metric_name": metric.metric_name}
    )

    class DraftMetric:
        def __init__(self, **fields):
            self.__dict__.update(fields)
            self.id = 5
            self.d3format = None

    monkeypatch.setattr(route_metric_candidate, "SqlMetric", DraftMetric)
    context.api = CandidateRouteAPI()

    status, payload = _invoke_route(context.api, "create_agent_metric")

    assert status == 201 and payload["result"]["provisional"] is True
    created_metric = context.dataset.metrics[-1]
    assert created_metric.metric_name == "average_temperature_2" and created_metric.expression == "MAX(temperature)"
    assert context.session.flushes == 1 and context.session.commits == 1
    contracts.propose_for_agent.assert_called_once_with(
        context.dataset,
        created_metric,
        "Maximum temperature.",
        "C",
        "AI Agent đề xuất khi trả lời: How warm?",
        context.user.id,
    )
    assert existing_metric in context.dataset.metrics


def test_agent_metric_route_rejects_nonaggregate_datasets(route_context, monkeypatch):
    import superset

    monkeypatch.setattr(superset.connectors.sqla.models, "SqlMetric", type("SqlMetric", (), {}), raising=False)
    from text_to_bi.superset_semantic_layer.modules.metric_management.routes import route_metric_candidate

    class CandidateRouteAPI(route_metric_candidate.MetricCandidateRoutes):
        def response(self, status, **payload):
            return status, payload

        def response_500(self, **payload):
            return self.response(500, **payload)

    context = route_context
    context.body["dataset_id"] = context.dataset.id
    monkeypatch.setattr(route_metric_candidate, "request", SimpleNamespace(get_json=lambda silent=True: context.body))
    monkeypatch.setattr(route_metric_candidate, "require_semantic_layer_query", lambda: None)
    monkeypatch.setattr(route_metric_candidate, "ensure_dictionary_tables", lambda: None)
    monkeypatch.setattr(route_metric_candidate, "require_dataset", lambda _: context.dataset)
    monkeypatch.setattr(
        route_metric_candidate,
        "dataset_dictionary_repository",
        lambda: SimpleNamespace(read=lambda _: SimpleNamespace(dataset_type="base")),
    )
    contracts = Mock()
    monkeypatch.setattr(route_metric_candidate, "MetricContractService", lambda: contracts)
    context.api = CandidateRouteAPI()

    assert _invoke_route(context.api, "create_agent_metric")[0] == 400
    contracts.read.assert_not_called()
