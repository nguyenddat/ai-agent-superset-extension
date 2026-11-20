import ast
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from catalog_source import MODULES_PATH, compile_into
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from text_to_bi.superset_semantic_layer.modules.glossary_management.exceptions import (
    GlossaryConflictError,
    GlossarySelfApprovalError,
    GlossaryTermGroupNotFoundError,
    GlossaryTermNotFoundError,
    GlossaryValidationError,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.services import (
    srv_glossary_group as glossary_groups,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.services import (
    srv_glossary_validation as validation,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_glossary_link import (
    link_fingerprint as glossary_link_fingerprint,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_glossary_link import (
    validated_links,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_glossary_term import (
    GlossaryTermService,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_glossary_validation import (
    expected_revision_of,
    normalize_glossary_payload,
    review_reason,
)

SERVICE_PATH = MODULES_PATH / "glossary_management" / "services" / "srv_glossary_term.py"
GROUP_SERVICE_PATH = MODULES_PATH / "glossary_management" / "services" / "srv_glossary_group.py"
REPOSITORY_PATHS = [
    MODULES_PATH / "glossary_management" / "repositories" / name
    for name in ("repo_glossary_term.py", "repo_glossary_revision.py")
]
VALIDATION_HELPERS = (
    "content_hash",
    "normalize_glossary_payload",
    "validated_links",
    "group_id_of",
    "normalize_group_payload",
    "MAX_REASON_LENGTH",
)


def _payload(**overrides):
    return {
        "canonical_name": "Revenue",
        "definition": "Recognized revenue.",
        "synonyms": [],
        "steward_id": None,
        "links": [{"dataset_id": 7, "kind": "dataset"}],
        **overrides,
    }


def _current_glossary_service(monkeypatch):
    from text_to_bi.superset_semantic_layer.modules.glossary_management.services import srv_glossary_term

    term_store = {}
    revision_store = {}
    events = []

    class Terms:
        def add(self, term):
            term.id = max(term_store, default=0) + 1
            term.group_id = term.group.id if term.group is not None else None
            term_store[term.id] = term

        def read(self, term_id):
            return term_store.get(term_id)

        def read_for_update(self, term_id):
            return self.read(term_id)

        def read_by_normalized_name(self, name):
            return next((term for term in term_store.values() if term.normalized_name == name), None)

        def read_in_group(self, group_id):
            return [term for term in term_store.values() if term.group_id == group_id]

    class Revisions:
        def create(self, values):
            revision_id = max(revision_store, default=0) + 1
            revision = SimpleNamespace(id=revision_id, term=term_store[values["term_id"]], **values)
            revision_store[revision_id] = revision
            return revision

        def read_current(self, term_id):
            return next(
                (
                    revision for revision in revision_store.values()
                    if revision.term_id == term_id and revision.is_current
                ),
                None,
            )

        def read_by_term(self, term_id):
            return [revision for revision in revision_store.values() if revision.term_id == term_id]

        def read_current_for_update(self, term_id):
            return self.read_current(term_id)

        def read_serving(self, term_id):
            return next(
                (
                    revision for revision in reversed(list(revision_store.values()))
                    if revision.term_id == term_id and revision.status == "approved"
                ),
                None,
            )

        def serving(self):
            latest_decided = {}
            for revision in revision_store.values():
                if revision.status in {"approved", "revoked"}:
                    latest_decided[revision.term_id] = revision
            return [revision for revision in latest_decided.values() if revision.status == "approved"]

    class Links:
        def create(self, _values, flush=True):
            return None

    class Groups:
        def require(self, group_id):
            raise AssertionError(f"unexpected group {group_id}")

        def place_term(self, *_):
            return None

    class Events:
        def create(self, revision, event_type, actor_id, reason=None):
            events.append(SimpleNamespace(
                revision_id=revision.id, revision_number=revision.revision_number, event_type=event_type,
                actor_id=actor_id, reason=reason,
            ))

        def read_author_id(self, revision):
            return next(
                (
                    event.actor_id for event in events
                    if event.revision_id == revision.id and event.event_type == "created"
                ),
                None,
            )

        def read_history(self, term_id):
            revision_ids = {revision.id for revision in revision_store.values() if revision.term_id == term_id}
            return [event for event in events if event.revision_id in revision_ids]

    monkeypatch.setattr(srv_glossary_term, "get_user", lambda user_id: object() if user_id in {7, 8} else None)
    monkeypatch.setattr(
        srv_glossary_term, "get_dataset", lambda dataset_id: SimpleNamespace(id=dataset_id, columns=[], metrics=[]),
    )
    # This in-memory service harness does not need SQLAlchemy mapper configuration or Superset's `tables` model.
    monkeypatch.setattr(
        srv_glossary_term,
        "GlossaryTerm",
        lambda **values: SimpleNamespace(id=None, group_id=values["group"].id if values["group"] else None, **values),
    )
    service = GlossaryTermService.__new__(GlossaryTermService)
    service.terms, service.revisions, service.links = Terms(), Revisions(), Links()
    service.groups, service.events = Groups(), Events()
    session = SimpleNamespace(commit=lambda: None)
    return service, session


def _current_glossary_group_service(term_service):
    groups_by_id = {}

    class Groups:
        def create(self, values):
            group = SimpleNamespace(id=max(groups_by_id, default=0) + 1, **values)
            groups_by_id[group.id] = group
            return group

        def read(self, group_id):
            return groups_by_id.get(group_id)

        def read_all(self):
            return list(groups_by_id.values())

        def read_by_normalized_name(self, name):
            return next((group for group in groups_by_id.values() if group.normalized_name == name), None)

        def update(self, group, values):
            for name, value in values.items():
                setattr(group, name, value)
            return group

        def delete(self, group):
            groups_by_id.pop(group.id)

    from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_glossary_group import (
        GlossaryGroupService,
    )

    groups = GlossaryGroupService.__new__(GlossaryGroupService)
    groups.groups = Groups()
    groups.terms, groups.revisions, groups.events = term_service.terms, term_service.revisions, term_service.events
    return groups, groups_by_id


def test_normalize_payload_trims_casefolds_and_deduplicates_synonyms():
    payload = normalize_glossary_payload(
        _payload(canonical_name="  Net Revenue ", synonyms=[" net sales ", "NET SALES", "revenue net"])
    )

    assert payload["canonical_name"] == "Net Revenue"
    assert payload["normalized_name"] == "net revenue"
    assert payload["synonyms"] == ["net sales", "revenue net"]


@pytest.mark.parametrize(
    "payload",
    [
        _payload(canonical_name=""),
        _payload(synonyms=[" revenue "]),
        _payload(links=[]),
        _payload(steward_id=True),
        # The removed provenance fields are refused rather than silently dropped.
        _payload(provenance="manual"),
        _payload(owner_id=1),
        _payload(source_reference="postgresql://admin:secret@db/internal"),
    ],
)
def test_normalize_payload_rejects_invalid_or_unknown_values(payload):
    with pytest.raises(GlossaryValidationError):
        normalize_glossary_payload(payload)


def test_the_revision_token_and_review_reason_are_read_from_the_request():
    assert expected_revision_of({"expected_revision": 4}) == 4
    for payload in (None, {}, {"expected_revision": True}, {"expected_revision": "4"}):
        with pytest.raises(GlossaryValidationError, match="expected_revision is required"):
            expected_revision_of(payload)
    assert review_reason({"reason": "  Định nghĩa sai.  "}) == "Định nghĩa sai."
    assert review_reason({"reason": "   "}) is None and review_reason(None) is None
    with pytest.raises(GlossaryValidationError):
        review_reason({"reason": "x" * 513})


def test_fingerprint_is_credential_free_and_stales_when_live_object_changes():
    dataset = SimpleNamespace(
        id=7,
        catalog="analytics",
        schema="public",
        table_name="daily_weather",
        sql=None,
        database=SimpleNamespace(id=2, database_name="warehouse", sqlalchemy_uri="postgresql://user:secret@host/db"),
        columns=[SimpleNamespace(column_name="temperature", is_active=True, expression=None)],
        metrics=[SimpleNamespace(id=19, metric_name="avg_temperature", expression="AVG(temperature)")],
    )
    fingerprint = glossary_link_fingerprint(dataset, "metric", dataset.metrics[0])

    assert "secret" not in fingerprint
    dataset.metrics[0].expression = "AVG(temperature_f)"
    assert glossary_link_fingerprint(dataset, "metric", dataset.metrics[0]) != fingerprint


def _weather_dataset():
    column = SimpleNamespace(id=86, column_name="quan_sat_id", is_active=True, expression=None)
    metric = SimpleNamespace(id=19, metric_name="observation_count", expression="COUNT(*)")
    return SimpleNamespace(id=11, columns=[column], metrics=[metric])


def test_validated_links_populates_only_the_matching_target_field():
    dataset = _weather_dataset()
    links = validated_links(
        [
            {"kind": "column", "dataset_id": 11, "column_name": "quan_sat_id"},
            {"kind": "metric", "dataset_id": 11, "metric_id": 19},
        ],
        lambda dataset_id: dataset if dataset_id == 11 else None,
        lambda _dataset, _metric: True,
    )

    assert (links[0]["column_name"], links[0]["metric_id"]) == ("quan_sat_id", None)
    assert (links[1]["column_name"], links[1]["metric_id"]) == (None, 19)


@pytest.mark.parametrize(
    "link",
    [
        {"kind": "column", "dataset_id": 11, "column_name": "missing"},
        {"kind": "metric", "dataset_id": 11, "metric_id": 999},
        {"kind": "dataset", "dataset_id": 99},
    ],
)
def test_validated_links_rejects_missing_live_targets(link):
    dataset = _weather_dataset()
    with pytest.raises(GlossaryValidationError, match="Invalid glossary link"):
        validated_links([link], lambda dataset_id: dataset if dataset_id == 11 else None, lambda *_: True)


def test_a_term_may_link_only_approved_metrics():
    dataset = _weather_dataset()
    link = {"kind": "metric", "dataset_id": 11, "metric_id": 19}

    with pytest.raises(GlossaryValidationError, match="approved metrics"):
        validated_links([link], lambda _: dataset, lambda _dataset, _metric: False)
    assert validated_links([link], lambda _: dataset, lambda _dataset, _metric: True)


def test_lifecycle_mutations_lock_the_term_and_its_current_revision():
    for path in REPOSITORY_PATHS:
        assert "with_for_update()" in path.read_text(encoding="utf-8")
    source = SERVICE_PATH.read_text(encoding="utf-8")
    service_class = next(
        node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlossaryTermService"
    )
    locked = next(
        node for node in service_class.body if isinstance(node, ast.FunctionDef) and node.name == "_locked_current"
    )
    assert "read_for_update" in ast.unparse(locked) and "read_current_for_update" in ast.unparse(locked)


def _sqlite_service(users=(7, 8)):
    base = declarative_base()

    class GlossaryTermGroup(base):
        __tablename__ = "glossary_term_group"
        id = Column(Integer, primary_key=True)
        name = Column(String, nullable=False)
        normalized_name = Column(String, nullable=False, unique=True)
        description = Column(String)

    class GlossaryTerm(base):
        __tablename__ = "glossary_term"
        id = Column(Integer, primary_key=True)
        canonical_name = Column(String, nullable=False)
        normalized_name = Column(String, nullable=False, unique=True)
        steward_id = Column(Integer)
        group_id = Column(Integer, ForeignKey("glossary_term_group.id"))
        group = relationship(GlossaryTermGroup)

    class GlossaryTermRevision(base):
        __tablename__ = "glossary_term_revision"
        __table_args__ = (UniqueConstraint("term_id", "revision_number"),)
        id = Column(Integer, primary_key=True)
        term_id = Column(Integer, ForeignKey("glossary_term.id"), nullable=False)
        revision_number = Column(Integer, nullable=False)
        definition = Column(String, nullable=False)
        synonyms = Column(JSON, nullable=False)
        content_hash = Column(String, nullable=False)
        status = Column(String, nullable=False)
        is_current = Column(Boolean, nullable=False)
        approver_id = Column(Integer)
        approved_at = Column(DateTime)
        revoker_id = Column(Integer)
        revoked_at = Column(DateTime)
        term = relationship(GlossaryTerm)

    class GlossaryTermLink(base):
        __tablename__ = "glossary_term_link"
        id = Column(Integer, primary_key=True)
        revision_id = Column(Integer, nullable=False)
        kind = Column(String, nullable=False)
        link_key = Column(String, nullable=False)
        dataset_id = Column(Integer, nullable=False)
        column_name = Column(String)
        metric_id = Column(Integer)
        fingerprint = Column(String, nullable=False)

    class GlossaryTermAuditEvent(base):
        __tablename__ = "glossary_term_audit_event"
        id = Column(Integer, primary_key=True)
        term_id = Column(Integer, nullable=False)
        revision_id = Column(Integer, nullable=False)
        event_type = Column(String, nullable=False)
        actor_id = Column(Integer)
        reason = Column(String)
        revision_number = Column(Integer, nullable=False)
        occurred_at = Column(DateTime, nullable=False)

    engine = create_engine("sqlite:///:memory:")
    base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    dataset = SimpleNamespace(id=7, table_name="daily_weather", columns=[], metrics=[])
    namespace = {
        "db": SimpleNamespace(session=session),
        "GlossaryTerm": GlossaryTerm,
        "GlossaryTermGroup": GlossaryTermGroup,
        "GlossaryTermRevision": GlossaryTermRevision,
        "GlossaryTermLink": GlossaryTermLink,
        "GlossaryTermAuditEvent": GlossaryTermAuditEvent,
        "datetime": datetime,
        "timezone": timezone,
        "IntegrityError": IntegrityError,
        "security_manager": SimpleNamespace(get_user_by_id=lambda user_id: object() if user_id in users else None),
        "get_dataset": lambda dataset_id: dataset if dataset_id == 7 else None,
        "glossary_metric_approved": lambda _dataset, _metric: True,
        **{
            name: (validated_links if name == "validated_links" else getattr(validation, name))
            for name in VALIDATION_HELPERS
        },
    }
    service = [
        node
        for path in (GROUP_SERVICE_PATH, SERVICE_PATH)
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.FunctionDef, ast.Assign))
    ]
    compile_into(namespace, *service)
    return SimpleNamespace(**namespace), session


def test_an_edit_of_an_approved_term_keeps_the_approved_revision_serving_until_its_draft_is_approved(monkeypatch):
    service, session = _current_glossary_service(monkeypatch)
    revisions = service.revisions
    first = service.create(_payload(steward_id=8), 7)
    session.commit()
    term_id = first.term_id
    assert revisions.read_serving(term_id) is None

    service.approve(term_id, 1, 8, None, True)
    session.commit()
    draft = service.update(term_id, _payload(definition="Revenue net of returns."), 1, 7)
    session.commit()

    assert (draft.revision_number, draft.status, draft.is_current) == (2, "draft", True)
    assert revisions.read_serving(term_id).revision_number == 1
    assert [revision.revision_number for revision in revisions.serving()] == [1]

    service.approve(term_id, 2, 8, None, True)
    session.commit()
    assert revisions.read_serving(term_id).revision_number == 2
    assert [revision.revision_number for revision in revisions.serving()] == [2]


def test_revoking_while_an_edit_waits_stops_the_serving_revision_and_keeps_the_draft(monkeypatch):
    service, session = _current_glossary_service(monkeypatch)
    revisions = service.revisions
    term_id = service.create(_payload(), 7).term_id
    service.approve(term_id, 1, 8, None, False)
    service.update(term_id, _payload(definition="Revenue net of returns."), 1, 7)
    session.commit()

    with pytest.raises(GlossaryValidationError, match="reason"):
        service.revoke(term_id, 2, 8, None)
    current = service.revoke(term_id, 2, 8, "Definition is incorrect.")
    session.commit()

    assert (current.revision_number, current.status) == (2, "draft")
    assert revisions.read_serving(term_id) is None and revisions.serving() == []
    events = service.events.read_history(term_id)
    assert [(event.event_type, event.revision_number) for event in events] == [
        ("created", 1),
        ("approved", 1),
        ("updated", 2),
        ("revoked", 1),
    ]
    with pytest.raises(GlossaryValidationError, match="approved revision"):
        service.revoke(term_id, 2, 8, "Again.")


def test_a_revoked_term_is_revised_by_a_new_draft_and_served_again_after_approval(monkeypatch):
    service, _ = _current_glossary_service(monkeypatch)
    term_id = service.create(_payload(), 7).term_id
    service.approve(term_id, 1, 8, None, False)
    service.revoke(term_id, 1, 8, "Incorrect definition")
    service.update(term_id, _payload(definition="Corrected."), 1, 7)
    service.approve(term_id, 2, 8, None, False)
    assert service.read_serving(term_id).definition == "Corrected."


def test_stale_revisions_names_and_stewards_are_refused(monkeypatch):
    service, _ = _current_glossary_service(monkeypatch)
    term_id = service.create(_payload(), 7).term_id

    with pytest.raises(GlossaryConflictError, match="changed"):
        service.update(term_id, _payload(), 2, 7)
    with pytest.raises(GlossaryConflictError, match="changed"):
        service.approve(term_id, 3, 8, None, False)
    with pytest.raises(GlossaryConflictError, match="already exists"):
        service.create(_payload(canonical_name=" revenue "), 7)
    with pytest.raises(GlossaryValidationError, match="canonical name cannot be changed"):
        service.update(term_id, _payload(canonical_name="Sales"), 1, 7)
    with pytest.raises(GlossaryValidationError, match="Unknown steward_id"):
        service.update(term_id, _payload(steward_id=99), 1, 7)
    with pytest.raises(GlossaryTermNotFoundError):
        service.approve(404, 1, 8, None, False)


def test_the_editor_names_the_steward(monkeypatch):
    service, _ = _current_glossary_service(monkeypatch)
    term_id = service.create(_payload(), 7).term_id
    service.update(term_id, _payload(steward_id=8), 1, 7)
    assert service.terms.read(term_id).steward_id == 8


@pytest.mark.parametrize("require_second_reviewer", [False, True])
def test_the_author_may_approve_their_own_draft_unless_a_second_reviewer_is_required(
    require_second_reviewer, monkeypatch,
):
    service, _ = _current_glossary_service(monkeypatch)
    term_id = service.create(_payload(), 7).term_id

    if require_second_reviewer:
        with pytest.raises(GlossarySelfApprovalError):
            service.approve(term_id, 1, 7, None, True)
        assert service.revisions.read_current(term_id).status == "draft"
    else:
        assert service.approve(term_id, 1, 7, None, False).approver_id == 7


def test_only_the_current_draft_can_be_approved(monkeypatch):
    service, _ = _current_glossary_service(monkeypatch)
    term_id = service.create(_payload(), 7).term_id
    service.approve(term_id, 1, 8, None, False)
    with pytest.raises(GlossaryValidationError, match="Only the current draft"):
        service.approve(term_id, 1, 8, None, False)


def test_a_group_has_a_trimmed_name_unique_without_case_and_an_optional_description():
    assert validation.normalize_group_payload({"name": "  Nhiệt   độ ", "description": "  "}) == {
        "name": "Nhiệt độ",
        "normalized_name": "nhiệt độ",
        "description": None,
    }
    for payload in (None, {}, {"name": "  "}, {"name": "x" * 256}, {"name": "A", "color": "red"}):
        with pytest.raises(GlossaryValidationError):
            validation.normalize_group_payload(payload)
    assert validation.group_id_of({"group_id": None}) is None and validation.group_id_of({"group_id": 3}) == 3
    with pytest.raises(GlossaryValidationError, match="Nhóm thuật ngữ không hợp lệ"):
        validation.group_id_of({"group_id": True})


def test_groups_are_created_renamed_and_refuse_a_name_another_group_has(monkeypatch):
    service, _ = _current_glossary_service(monkeypatch)
    groups, _ = _current_glossary_group_service(service)
    service.groups = groups
    heat = groups.create({"name": "Temperature", "description": "Ways to describe temperature"})
    rain = groups.create({"name": "Rain"})

    with pytest.raises(GlossaryConflictError):
        groups.create({"name": " temperature "})
    with pytest.raises(GlossaryConflictError):
        groups.update(rain.id, {"name": "Temperature"})
    renamed = groups.update(heat.id, {"name": "Air temperature", "description": None})
    assert (renamed.name, renamed.description) == ("Air temperature", None)
    with pytest.raises(GlossaryTermGroupNotFoundError):
        groups.update(404, {"name": "Other"})

def test_moving_an_approved_term_keeps_it_serving_without_a_new_revision_and_audits_the_move(monkeypatch):
    service, _ = _current_glossary_service(monkeypatch)
    groups, _ = _current_glossary_group_service(service)
    service.groups = groups
    heat = groups.create({"name": "Temperature"})
    rain = groups.create({"name": "Rain"})
    term_id = service.create(_payload(group_id=heat.id), 7).term_id
    service.approve(term_id, 1, 8, None, False)
    assert service.terms.read(term_id).group_id == heat.id

    groups.move_term(term_id, rain.id, 8)
    groups.move_term(term_id, rain.id, 8)
    groups.move_term(term_id, None, 8)

    assert [revision.revision_number for revision in service.revisions.read_by_term(term_id)] == [1]
    assert service.revisions.read_serving(term_id).status == "approved"
    events = service.events.read_history(term_id)
    arrow = chr(0x2192)
    assert [(event.event_type, event.reason) for event in events] == [
        ("created", None),
        ("approved", None),
        ("moved", f"Temperature {arrow} Rain"),
        ("moved", f"Rain {arrow} {glossary_groups.UNGROUPED}"),
    ]
    with pytest.raises(GlossaryTermGroupNotFoundError):
        groups.move_term(term_id, 404, 8)
    with pytest.raises(GlossaryTermNotFoundError):
        groups.move_term(404, rain.id, 8)

def test_an_edit_moves_the_term_at_once_while_its_draft_waits_and_keeps_the_group_when_it_names_none(monkeypatch):
    service, _ = _current_glossary_service(monkeypatch)
    groups, _ = _current_glossary_group_service(service)
    service.groups = groups
    heat = groups.create({"name": "Temperature"})
    term_id = service.create(_payload(), 7).term_id
    service.approve(term_id, 1, 8, None, False)
    service.update(term_id, _payload(definition="Revenue net of returns.", group_id=heat.id), 1, 7)
    assert service.terms.read(term_id).group_id == heat.id
    assert service.revisions.read_serving(term_id).revision_number == 1

    service.update(term_id, _payload(definition="Revenue after returns."), 2, 7)
    assert service.terms.read(term_id).group_id == heat.id
    with pytest.raises(GlossaryTermGroupNotFoundError):
        service.create(_payload(canonical_name="Sales", group_id=404), 7)

def test_deleting_a_group_leaves_its_terms_ungrouped_and_approved(monkeypatch):
    service, _ = _current_glossary_service(monkeypatch)
    groups, group_rows = _current_glossary_group_service(service)
    service.groups = groups
    heat = groups.create({"name": "Temperature"})
    first = service.create(_payload(group_id=heat.id), 7).term_id
    second = service.create(_payload(canonical_name="Sales", group_id=heat.id), 7).term_id
    service.approve(first, 1, 8, None, False)

    assert groups.delete(heat.id, 8) == [first, second]

    assert service.terms.read(first).group_id is None and service.terms.read(second).group_id is None
    assert groups.read_all() == [] and group_rows == {}
    assert service.revisions.read_serving(first).revision_number == 1
    events = service.events.read_history(second)
    assert (events[-1].event_type, events[-1].reason) == (
        "moved",
        f"Temperature {chr(0x2192)} {glossary_groups.UNGROUPED}",
    )
    with pytest.raises(GlossaryTermGroupNotFoundError):
        groups.delete(heat.id, 8)
