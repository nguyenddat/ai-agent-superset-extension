from datetime import datetime, timezone
from typing import Any

from ....common.utils.type_formatter import iso_datetime
from ...questions.dependencies import question_repository
from ...superset.services.dashboards import dashboard_titles
from ...superset.services.users import user_names
from ..dependencies import user_definition_repository
from ..exceptions import UserDefinitionNotFoundError
from ..models import AgentUserDefinition
from .conditions import conditions_for
from .parsing import parse_definition


def serialize_definition(definition: AgentUserDefinition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "kind": definition.kind,
        "name": definition.name,
        "concept": definition.concept,
        "definition": definition.definition,
        "conditions": definition.conditions,
        "dashboard_id": definition.dashboard_id,
        "source_question_id": definition.source_question_id,
        "review_status": definition.review_status,
        "updated_on": iso_datetime(definition.updated_on),
    }


def definitions_on_dashboard(user_id: int, dashboard_id: int) -> list[AgentUserDefinition]:
    return user_definition_repository().for_dashboard(user_id, dashboard_id)


def definitions_for_agent(user_id: int, dashboard_id: int) -> list[dict[str, Any]]:
    keys = ("id", "kind", "name", "concept", "definition", "conditions")
    return [{key: getattr(item, key) for key in keys} for item in definitions_on_dashboard(user_id, dashboard_id)]


def require_own_definition(definition_id: int, user_id: int) -> AgentUserDefinition:
    definition = user_definition_repository().own(definition_id, user_id)
    if definition is None:
        raise UserDefinitionNotFoundError()
    return definition


def _reopen(definition: AgentUserDefinition) -> None:
    definition.review_status = "pending"
    definition.reviewed_by = None
    definition.reviewed_on = None
    definition.updated_on = datetime.now(timezone.utc)


def save_confirmed_definitions(
    confirmed: list[dict[str, Any]],
    *,
    user_id: int,
    dashboard_id: int,
    question_id: int,
    session_id: int,
    cookie_header: str,
) -> None:
    repository = user_definition_repository()
    existing = {(item.kind, item.name.casefold()): item for item in repository.for_dashboard(user_id, dashboard_id)}
    conditions = conditions_for(confirmed, user_id, cookie_header)
    for item, item_conditions in zip(confirmed, conditions):
        definition = existing.get((item["kind"], item["name"].casefold()))
        if definition is None:
            definition = AgentUserDefinition(user_id=user_id, dashboard_id=dashboard_id, kind=item["kind"])
            # Not flushed yet: the required fields are set just below.
            repository.add(definition, flush=False)
        definition.name = item["name"]
        definition.concept = item["concept"]
        definition.definition = item["definition"]
        definition.conditions = item_conditions
        definition.source_question_id = question_id
        definition.source_session_id = session_id
        _reopen(definition)


def update_definition(definition: AgentUserDefinition, body: Any, cookie_header: str) -> AgentUserDefinition:
    item = parse_definition({**(body if isinstance(body, dict) else {}), "kind": definition.kind})
    if item["definition"] != definition.definition or definition.conditions is None:
        # New words may mean a new threshold, so the conditions are worked out again from them.
        asked = {**item, "concept": item["concept"] or definition.concept}
        definition.conditions = conditions_for([asked], definition.user_id, cookie_header)[0]
    definition.name = item["name"]
    definition.concept = item["concept"] or definition.concept
    definition.definition = item["definition"]
    _reopen(definition)
    return definition


def definitions_for_review() -> list[dict[str, Any]]:
    definitions = user_definition_repository().recently_changed()
    user_name = user_names()
    dashboards = dashboard_titles({item.dashboard_id for item in definitions})
    questions = question_repository().texts({item.source_question_id for item in definitions} - {None})
    return [
        {
            **serialize_definition(item),
            "user_id": item.user_id,
            "defined_by": user_name(item.user_id),
            "dashboard_title": dashboards.get(item.dashboard_id),
            "question": questions.get(item.source_question_id),
            "reviewed_by": user_name(item.reviewed_by),
            "reviewed_on": iso_datetime(item.reviewed_on),
        }
        for item in definitions
    ]


def set_review_status(definition_ids: list[int], status: str, reviewer_id: int) -> int:
    reviewed = status != "pending"
    return user_definition_repository().update_by_ids(definition_ids, {
        "review_status": status,
        "reviewed_by": reviewer_id if reviewed else None,
        "reviewed_on": datetime.now(timezone.utc) if reviewed else None,
    })
