import importlib
import inspect
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from text_to_bi.superset_semantic_layer.modules.expert_rule_management.exceptions import (
    ExpertRuleConflictError,
    ExpertRuleGroupNotFoundError,
    ExpertRuleNotFoundError,
    ExpertRuleSelfApprovalError,
    ExpertRuleValidationError,
)
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import srv_expert_rule as service
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import srv_expert_rule_group as group_service
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import srv_expert_rule_link as rule_links
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import srv_expert_rule_validation as validation


def _payload(**overrides):
    value = {
        "name": "Exclude provisional observations",
        "dataset_id": 7,
        "schema_version": 2,
        "conditions": [
            {"field_ref": {"column_dictionary_id": 70}, "operator": "equals", "value_type": "string", "value": "final"}
        ],
        "exceptions": [{"when": "station is under maintenance", "outcome": "review manually"}],
        "examples": [{"question": "What is the final average temperature?", "intent": "aggregate"}],
        "glossary_term_ids": [3],
        "metric_ids": [9],
    }
    value.update(overrides)
    return value


def test_normalize_payload_accepts_declarative_rule_only():
    normalized = validation.normalize_rule_payload(_payload())
    assert normalized["name"] == "Exclude provisional observations"
    assert normalized["conditions"][0]["operator"] == "equals"


def test_v2_conditions_are_typed_and_v1_adapter_requires_exact_same_dataset_column():
    column = lambda reference: (
        [SimpleNamespace(id=70, dataset_id=7, column_name="observation_status")]
        if reference == "observation_status"
        else SimpleNamespace(id=70, dataset_id=7, column_name="observation_status")
        if reference == 70
        else None
    )
    normalized = validation.normalize_rule_payload(_payload(), column)
    assert normalized["schema_version"] == 2
    assert normalized["conditions"][0]["field_ref"]["column_dictionary_id"] == 70
    legacy = _payload(
        schema_version=1, conditions=[{"field": "observation_status", "operator": "equals", "value": "final"}]
    )
    assert validation.normalize_rule_payload(legacy, column)["conditions"] == normalized["conditions"]
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(
            _payload(
                conditions=[
                    {
                        "field_ref": {"column_dictionary_id": 8},
                        "operator": "equals",
                        "value_type": "string",
                        "value": "x",
                        "sql": "SELECT 1",
                    }
                ]
            ),
            column,
        )
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(
            _payload(), lambda _: SimpleNamespace(id=70, dataset_id=8, column_name="observation_status")
        )


@pytest.mark.parametrize(
    "text",
    [
        "lọc các giao dịch cuối cùng",
        "tổng doanh thu theo tháng",
        "beginning balance",
        "Update the monthly report",
        "with seasonal adjustments",
        "set priorities for the team",
        "please set priorities for the team",
        "review with context",
        "do not include provisional records",
        "show monthly revenue",
        "set expectations",
    ],
)
def test_normalize_payload_accepts_natural_language(text):
    normalized = validation.normalize_rule_payload(_payload(exceptions=[{"when": text, "outcome": "review manually"}]))
    assert normalized["exceptions"][0]["when"] == text


@pytest.mark.parametrize(
    "payload",
    [
        _payload(conditions="SELECT * FROM users"),
        _payload(examples=[{"question": "x", "sql": "SELECT * FROM secrets"}]),
        _payload(exceptions=[{"when": "https://user:secret@example.test", "outcome": "x"}]),
        _payload(exceptions=[{"when": "VALUES (1)", "outcome": "x"}]),
        _payload(examples=[{"question": "x", "intent": "https://example.test/?api_key=secret"}]),
        _payload(examples=[{"question": "x", "intent": "Bearer abc.def.ghi"}]),
        _payload(metric_ids=[9, 9]),
        _payload(dataset_id=True),
    ],
)
def test_normalize_payload_rejects_executable_secrets_and_invalid_links(payload):
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(payload)


@pytest.mark.parametrize(
    "command",
    [
        "PRAGMA database_list",
        "WITH records AS (SELECT 1) SELECT * FROM records",
        "SHOW DATABASES",
        "DESCRIBE weather_observations",
        "EXPLAIN SELECT * FROM observations",
        "TRUNCATE TABLE observations",
        "MERGE INTO observations USING source ON 1 = 1",
        "CALL refresh_weather()",
        "VACUUM",
        "ANALYZE observations",
        "DEALLOCATE ALL",
        "LISTEN updates",
        "NOTIFY updates",
        "RESET ALL",
        "DISCARD ALL",
        "REINDEX TABLE records",
    ],
)
def test_normalize_payload_rejects_sql_command_families(command):
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(_payload(exceptions=[{"when": command, "outcome": "ignore"}]))


@pytest.mark.parametrize(
    "text",
    [
        "Please use SELECT * FROM observations",
        "The query is WITH observations AS (SELECT 1) SELECT * FROM observations",
        "Run UPDATE observations SET status = 'final'",
        "Avoid DELETE FROM observations",
        "Use INSERT INTO observations VALUES (1)",
        "Create CREATE TABLE scratch (id int)",
    ],
)
def test_normalize_payload_rejects_embedded_sql_grammar(text):
    """SQL-shaped fragments remain unsafe even when surrounded by prose."""
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(_payload(exceptions=[{"when": text, "outcome": "ignore"}]))


@pytest.mark.parametrize(
    "command",
    [
        "BEGIN",
        "BEGIN\nTRANSACTION",
        "START\tTRANSACTION",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT point",
        "SET TRANSACTION READ ONLY",
        "LOCK TABLE records",
        "DECLARE cursor",
        "DO $$",
        "EXEC task",
        "EXECUTE task",
        "CALL task()",
        "COPY records",
        "LOAD DATA",
        "CREATE TABLE x (id int)",
        "INSERT INTO records VALUES (1)",
        "UPDATE records SET x = 1",
        "DELETE FROM records",
        "SELECT * FROM records",
        "WITH items AS (SELECT 1) SELECT * FROM items",
        "-- comment",
        "# comment",
        "/* comment */",
        "statement; next",
    ],
)
def test_normalize_payload_rejects_sql_control_syntax(command):
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(_payload(examples=[{"question": command, "intent": "aggregate"}]))


@pytest.mark.parametrize(
    "command",
    [
        "BEGIN TRANSACTION",
        "START TRANSACTION",
        "COMMIT now",
        "ROLLBACK WORK",
        "SAVEPOINT retry_point",
        "SET TRANSACTION READ ONLY",
        "SET ROLE administrator",
        "SET search_path TO private",
        "LOCK TABLE records",
        "DECLARE result_cursor",
        "DO LANGUAGE plpgsql",
        "EXECUTE scheduled_task",
        "CALL refresh_weather()",
        "PRAGMA database_list",
        "VACUUM",
        "COPY records",
        "LOAD DATA",
        "ALTER SYSTEM SET work_mem = '1MB'",
        "REINDEX DATABASE analytics",
        "DEALLOCATE PREPARE prepared_rule",
    ],
)
def test_normalize_payload_rejects_prose_prefixed_control_commands(command):
    """Control grammar remains unsafe when a user prefixes it with prose."""
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(_payload(exceptions=[{"when": f"Please {command}", "outcome": "ignore"}]))


@pytest.mark.parametrize(
    "command",
    [
        "BEGIN",
        "SELECT 1",
        "SELECT a + b FROM records",
        "CREATE TEMPORARY TABLE scratch (id int)",
        "DROP MATERIALIZED VIEW monthly_rollup",
        "TRUNCATE records",
        "COPY (SELECT 1)",
        "SHOW DATABASES",
        "DESCRIBE records",
        "EXPLAIN SELECT 1",
        "ANALYZE records",
        "SELECT count(*) FROM records",
        "SELECT COALESCE(a, b) FROM records",
        "SELECT a::text FROM records",
        "SELECT now()",
        "SELECT current_user",
        "SELECT count(*)",
        "SELECT CAST(1 AS text)",
        "SELECT pg_sleep(1)",
        "CREATE UNIQUE INDEX x ON y(z)",
        "DROP IF EXISTS TABLE foo",
        "SHOW ALL",
        "SHOW search_path",
        "VALUES (1)",
        "LOAD file",
    ],
)
def test_normalize_payload_rejects_prose_prefixed_sql_statement_grammar(command):
    """Executable statement grammar is unsafe even after an explanatory prefix."""
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(_payload(exceptions=[{"when": f"Please {command}", "outcome": "ignore"}]))


@pytest.mark.parametrize("command", ["SHOW ALL", "LOAD file"])
def test_normalize_payload_rejects_dialect_commands_without_optional_parser(command):
    """Dialect commands are unsafe without an optional parser runtime dependency."""
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(_payload(exceptions=[{"when": f"Please {command}", "outcome": "ignore"}]))


def test_normalize_payload_constrains_condition_operator_to_enum():
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(
            _payload(conditions=[{"field": "status", "operator": "arbitrary", "value": "final"}])
        )


@pytest.mark.parametrize("field", ["name", "conditions", "exceptions", "examples"])
def test_normalize_payload_accepts_sql_words_when_they_are_ordinary_prose(field):
    text = "Update the monthly report with seasonal adjustments"
    payload = _payload()
    if field == "name":
        payload["name"] = text
    elif field == "conditions":
        payload["conditions"] = [
            {"field_ref": {"column_dictionary_id": 70}, "operator": "equals", "value_type": "string", "value": text}
        ]
    elif field == "exceptions":
        payload["exceptions"] = [{"when": text, "outcome": "set expectations"}]
    else:
        payload["examples"] = [{"question": text, "intent": "show monthly revenue"}]
    assert validation.normalize_rule_payload(payload)


def test_validate_links_requires_approved_same_dataset_objects(monkeypatch):
    payload = validation.normalize_rule_payload(_payload())
    monkeypatch.setattr(rule_links, "get_dataset", lambda dataset_id: SimpleNamespace(id=dataset_id) if dataset_id == 7 else None)
    monkeypatch.setattr(rule_links, "glossary_links", lambda _: [SimpleNamespace(status="approved", is_current=True, dataset_id=7)])
    monkeypatch.setattr(rule_links, "approved_metric", lambda _: SimpleNamespace(dataset_id=7, status="approved"))
    rule_links.validate_semantic_links(payload)

    monkeypatch.setattr(rule_links, "glossary_links", lambda _: [])
    with pytest.raises(ExpertRuleValidationError):
        rule_links.validate_semantic_links(payload)
    monkeypatch.setattr(rule_links, "glossary_links", lambda _: [SimpleNamespace(status="approved", is_current=True, dataset_id=7)])
    monkeypatch.setattr(rule_links, "approved_metric", lambda _: SimpleNamespace(dataset_id=8, status="approved"))
    with pytest.raises(ExpertRuleValidationError):
        rule_links.validate_semantic_links(payload)


def test_validate_links_selects_a_matching_current_glossary_link_from_multiple_links(monkeypatch):
    payload = validation.normalize_rule_payload(_payload())
    monkeypatch.setattr(rule_links, "get_dataset", lambda dataset_id: SimpleNamespace(id=dataset_id) if dataset_id == 7 else None)
    glossary = [
        SimpleNamespace(status="approved", is_current=True, dataset_id=2),
        SimpleNamespace(status="approved", is_current=True, dataset_id=7),
    ]
    monkeypatch.setattr(rule_links, "glossary_links", lambda _: glossary)
    monkeypatch.setattr(rule_links, "approved_metric", lambda _: SimpleNamespace(dataset_id=7, status="approved"))
    rule_links.validate_semantic_links(payload)

    monkeypatch.setattr(rule_links, "glossary_links", lambda _: glossary[:1])
    with pytest.raises(ExpertRuleValidationError):
        rule_links.validate_semantic_links(payload)


def test_discoverability_needs_approved_current_and_live_links(monkeypatch):
    rule = SimpleNamespace(status="approved", is_current=True)
    links = [SimpleNamespace(fingerprint="live", dataset_id=7)]
    monkeypatch.setattr(rule_links, "live_fingerprint", lambda _: "live")
    assert rule_links.rule_is_discoverable(rule, links)
    rule.status = "revoked"
    assert not rule_links.rule_is_discoverable(rule, links)
    rule.status = "approved"
    monkeypatch.setattr(rule_links, "live_fingerprint", lambda _: "changed")
    assert not rule_links.rule_is_discoverable(rule, links)


def test_discoverable_rules_keep_live_same_dataset_links_and_omit_stale_or_inaccessible(monkeypatch):
    rules, _, _, links_by_revision, _ = _current_rule_service(monkeypatch)
    visible = rules.create(_payload(), 11)
    stale = rules.create(_payload(name="Exclude provisional stations"), 11)
    inaccessible = rules.create(_payload(name="Exclude hidden stations", dataset_id=8), 11)
    for revision in (visible, stale, inaccessible):
        rules.approve(revision.rule_id, 1, 12, "reviewed", False)

    links_by_revision[visible.id].append(
        SimpleNamespace(id=20, kind="glossary", target_id=3, dataset_id=7, fingerprint="live")
    )
    links_by_revision[stale.id][0].fingerprint = "old"
    monkeypatch.setattr(service, "get_dataset", lambda dataset_id: SimpleNamespace(id=dataset_id))
    monkeypatch.setattr(service, "can_access_dataset", lambda dataset: dataset.id == 7)
    monkeypatch.setattr(service, "linked_target_authorized", lambda link: link.dataset_id == 7)
    monkeypatch.setattr(rule_links, "live_fingerprint", lambda link: link.fingerprint if link.fingerprint == "live" else "changed")

    discovered = rules.read_discoverable()
    assert [(rule.id, revision.id) for rule, revision, _ in discovered] == [(visible.rule_id, visible.id)]
    assert {link.kind for link in discovered[0][2]} == {"dataset", "glossary"}


def test_mutations_use_row_lock_and_expected_revision():
    repositories = Path(service.__file__).parents[1] / "repositories"
    for repository in ("repo_expert_rule.py", "repo_expert_rule_revision.py"):
        assert "with_for_update()" in (repositories / repository).read_text(encoding="utf-8")
    assert "read_for_update" in inspect.getsource(service.ExpertRuleService._locked_current)
    for name in ("update", "approve", "revoke"):
        assert "expected_revision" in inspect.getsource(getattr(service.ExpertRuleService, name))


def _lifecycle_session(monkeypatch):
    """Use disposable SQLite tables; never import or connect to Superset metadata."""
    base = declarative_base()

    class Group(base):
        __tablename__ = "groups"
        id = Column(Integer, primary_key=True)
        name = Column(String, nullable=False)
        normalized_name = Column(String, nullable=False, unique=True)
        description = Column(String)

    class Rule(base):
        __tablename__ = "rules"
        id = Column(Integer, primary_key=True)
        normalized_name = Column(String, nullable=False, unique=True)
        dataset_id = Column(Integer, nullable=False)
        group_id = Column(Integer, ForeignKey("groups.id"))
        group = relationship(Group)

    class Revision(base):
        __tablename__ = "revisions"
        id = Column(Integer, primary_key=True)
        rule_id = Column(Integer, nullable=False)
        revision_number = Column(Integer, nullable=False)
        lifecycle_version = Column(Integer, nullable=False)
        name = Column(String, nullable=False)
        conditions = Column(JSON, nullable=False)
        exceptions = Column(JSON, nullable=False)
        examples = Column(JSON, nullable=False)
        content_hash = Column(String, nullable=False)
        status = Column(String, nullable=False)
        is_current = Column(Boolean, nullable=False)
        approver_id = Column(Integer)
        approved_at = Column(String)
        revoker_id = Column(Integer)
        revoked_at = Column(String)

    class Link(base):
        __tablename__ = "links"
        id = Column(Integer, primary_key=True)
        revision_id = Column(Integer, nullable=False)
        kind = Column(String, nullable=False)
        target_id = Column(Integer, nullable=False)
        dataset_id = Column(Integer, nullable=False)
        fingerprint = Column(String, nullable=False)

    class Audit(base):
        __tablename__ = "audit"
        id = Column(Integer, primary_key=True)
        rule_id = Column(Integer, nullable=False)
        revision_id = Column(Integer, nullable=False)
        event_type = Column(String, nullable=False)
        actor_id = Column(Integer)
        reason = Column(String)
        revision_number = Column(Integer, nullable=False)
        lifecycle_version = Column(Integer, nullable=False)
        occurred_at = Column(String, nullable=False)

    engine = create_engine("sqlite:///:memory:")
    base.metadata.create_all(engine)
    module = types.ModuleType("text_to_bi.superset_semantic_layer.modules.expert_rule_management.models")
    module.ExpertRule, module.ExpertRuleRevision = Rule, Revision
    module.ExpertRuleLink, module.ExpertRuleAuditEvent, module.ExpertRuleGroup = Link, Audit, Group
    _track_parent_module_attribute(monkeypatch, module.__name__, module)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    # A repository binds its model when imported, so import the repositories again with these tables.
    for name in [name for name in sys.modules if name.startswith(f"{service.__package__[:-9]}.repositories.")]:
        _track_parent_module_attribute(monkeypatch, name, getattr(sys.modules[name.rsplit(".", 1)[0]], name.rsplit(".", 1)[1], None))
        monkeypatch.delitem(sys.modules, name)
    return sessionmaker(bind=engine)(), Rule, Revision, Audit


def _track_parent_module_attribute(monkeypatch, module_name, replacement):
    """Restore package attributes as well as sys.modules when tests swap model modules."""
    parent_name, attribute = module_name.rsplit(".", 1)
    parent = importlib.import_module(parent_name)
    monkeypatch.setattr(parent, attribute, replacement, raising=False)


def _current_rule_service(monkeypatch):
    """Run the production lifecycle service against small repository doubles."""
    rules_by_id, revisions_by_id, links_by_revision, events = {}, {}, {}, []

    class Rules:
        def add(self, rule):
            rule.id = max(rules_by_id, default=0) + 1
            rules_by_id[rule.id] = rule

        def read(self, rule_id):
            return rules_by_id.get(rule_id)

        def read_fresh(self, rule_id):
            return self.read(rule_id)

        def read_for_update(self, rule_id):
            return self.read(rule_id)

        def read_by_normalized_name(self, name):
            return next((rule for rule in rules_by_id.values() if rule.normalized_name == name), None)

        def read_in_group(self, group_id):
            return [rule for rule in rules_by_id.values() if rule.group_id == group_id]

    class Revisions:
        def create(self, values):
            revision_id = max(revisions_by_id, default=0) + 1
            revision = SimpleNamespace(id=revision_id, **values)
            revisions_by_id[revision_id] = revision
            return revision

        def read_current(self, rule_id):
            return next((revision for revision in revisions_by_id.values() if revision.rule_id == rule_id and revision.is_current), None)

        def read_current_for_update(self, rule_id):
            return self.read_current(rule_id)

        def read_all_approved_current(self):
            return [revision for revision in revisions_by_id.values() if revision.status == "approved" and revision.is_current]

    class Links:
        def create(self, values, flush=True):
            link = SimpleNamespace(id=sum(map(len, links_by_revision.values())) + 1, **values)
            links_by_revision.setdefault(link.revision_id, []).append(link)
            return link

        def read_by_revision(self, revision_id):
            return links_by_revision.get(revision_id, [])

    class Groups:
        def require(self, group_id):
            raise AssertionError(f"unexpected group {group_id}")

    class Events:
        def create(self, revision, event_type, actor_id, reason=None):
            events.append(SimpleNamespace(
                rule_id=revision.rule_id, revision_id=revision.id, revision_number=revision.revision_number,
                lifecycle_version=revision.lifecycle_version, event_type=event_type, actor_id=actor_id, reason=reason,
            ))

        def read_author_id(self, revision):
            return next(
                (event.actor_id for event in events if event.revision_id == revision.id and event.event_type in {"created", "updated"}),
                None,
            )

    monkeypatch.setattr(service, "ExpertRule", lambda **values: SimpleNamespace(id=None, group=None, group_id=None, **values))
    monkeypatch.setattr(service, "with_term_metrics", lambda payload: payload)
    monkeypatch.setattr(service, "validate_semantic_links", lambda _: None)
    monkeypatch.setattr(
        service,
        "column_resolver",
        lambda dataset_id: lambda reference: SimpleNamespace(id=reference, dataset_id=dataset_id, column_name="status"),
    )
    monkeypatch.setattr(service, "rule_links", lambda values: [
        {"kind": "dataset", "target_id": values["dataset_id"], "dataset_id": values["dataset_id"], "fingerprint": "live"}
    ])
    monkeypatch.setattr(service, "live_fingerprint", lambda _: "live")
    instance = service.ExpertRuleService.__new__(service.ExpertRuleService)
    instance.rules, instance.revisions, instance.links = Rules(), Revisions(), Links()
    instance.groups, instance.events = Groups(), Events()
    return instance, rules_by_id, revisions_by_id, links_by_revision, events


def _current_rule_group_service(rule_service):
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

    group_service_instance = group_service.ExpertRuleGroupService.__new__(group_service.ExpertRuleGroupService)
    group_service_instance.groups = Groups()
    group_service_instance.rules = rule_service.rules
    group_service_instance.revisions = rule_service.revisions
    group_service_instance.events = rule_service.events
    return group_service_instance, groups_by_id


def test_service_lifecycle_create_update_approve_revoke_and_audit(monkeypatch):
    rules, rule_rows, revisions, _links, events = _current_rule_service(monkeypatch)
    created = rules.create(_payload(), 11)
    assert created.revision_number == created.lifecycle_version == 1
    with pytest.raises(ExpertRuleValidationError, match="already exists"):
        rules.create(_payload(), 11)
    assert len(rule_rows) == 1

    updated = rules.update(created.rule_id, _payload(name="Exclude provisional records"), 1, 12)
    assert updated.revision_number == updated.lifecycle_version == 2
    assert revisions[created.id].is_current is False
    with pytest.raises(ExpertRuleConflictError):
        rules.update(created.rule_id, _payload(name="new"), 1, 12)

    # A second caller that retained the create token cannot approve the update.
    with pytest.raises(ExpertRuleConflictError):
        rules.approve(created.rule_id, 1, 13, "checked", False)
    rules.approve(created.rule_id, 2, 13, "checked", False)
    assert updated.status == "approved" and updated.lifecycle_version == 3
    with pytest.raises(ExpertRuleConflictError):
        rules.revoke(created.rule_id, 2, 14, "superseded")
    rules.revoke(created.rule_id, 3, 14, "superseded")
    # A revoked rule stays current so it can be corrected and reviewed again; discovery skips it by status.
    assert updated.status == "revoked" and updated.is_current is True and updated.lifecycle_version == 4
    assert [event.event_type for event in events] == [
        "created",
        "updated",
        "approved",
        "revoked",
    ]
    assert [event.lifecycle_version for event in events] == [1, 2, 3, 4]


def _lifecycle_resolvers():
    dataset = lambda key: SimpleNamespace(id=key) if key == 7 else None
    glossary = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 3 else None
    metric = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 9 else None
    fingerprint = lambda kind, target_id, dataset_id: f"{kind}:{target_id}:{dataset_id}"
    return dataset, glossary, metric, fingerprint


def test_the_author_may_approve_unless_a_second_reviewer_is_required(monkeypatch):
    rules, _, _, _, events = _current_rule_service(monkeypatch)
    created = rules.create(_payload(), 11)
    with pytest.raises(ExpertRuleSelfApprovalError):
        rules.approve(created.rule_id, 1, 11, None, require_second_reviewer=True)

    # Whoever edited the latest revision is its author, even if someone else created the rule.
    updated = rules.update(created.rule_id, _payload(name="Exclude draft observations"), 1, 12)
    assert events[-1].actor_id == 12
    with pytest.raises(ExpertRuleSelfApprovalError):
        rules.approve(created.rule_id, 2, 12, None, require_second_reviewer=True)
    rules.approve(created.rule_id, 2, 11, None, require_second_reviewer=True)
    assert updated.status == "approved" and updated.approver_id == 11


def test_a_rename_moves_the_rule_name_key_and_refuses_another_rules_name(monkeypatch):
    rules, rule_rows, _, _, _ = _current_rule_service(monkeypatch)
    created = rules.create(_payload(), 11)
    other = rules.create(_payload(name="Exclude test stations"), 11)

    rules.update(created.rule_id, _payload(name="Exclude  Provisional rows"), 1, 11)
    assert rule_rows[created.rule_id].normalized_name == "exclude provisional rows"
    # The old name is free again.
    rules.create(_payload(), 11)

    with pytest.raises(ExpertRuleValidationError, match="already exists"):
        rules.update(other.rule_id, _payload(name="exclude provisional rows"), 1, 11)
    assert rule_rows[other.rule_id].normalized_name == "exclude test stations"


def test_a_single_administrator_approves_their_own_draft_by_default(monkeypatch):
    rules, *_ = _current_rule_service(monkeypatch)
    created = rules.create(_payload(), 11)
    rules.approve(created.rule_id, 1, 11, None, False)
    assert created.status == "approved" and created.approver_id == 11


def test_a_revoked_rule_can_be_corrected_into_a_new_draft(monkeypatch):
    rules, _, revisions, _, _ = _current_rule_service(monkeypatch)
    created = rules.create(_payload(), 11)
    rules.approve(created.rule_id, 1, 12, "reviewed", False)
    rules.revoke(created.rule_id, 2, 12, "No longer applicable")

    corrected = rules.update(created.rule_id, _payload(name="Exclude provisional rows"), 3, 11)
    assert corrected.status == "draft" and corrected.revision_number == 2 and corrected.lifecycle_version == 4
    assert revisions[created.id].is_current is False and corrected.is_current is True


@pytest.mark.parametrize(
    "reason",
    [
        "https://user:secret@example.test",
        "Bearer private-token",
        "BEGIN TRANSACTION",
        "Please SET ROLE administrator",
        "Please ALTER SYSTEM SET work_mem = '1MB'",
        "Please DEALLOCATE PREPARE prepared_rule",
        "x" * 513,
    ],
)
def test_transition_rejects_unsafe_reason_before_audit_or_status_mutation(monkeypatch, reason):
    rules, _, _, _, events = _current_rule_service(monkeypatch)
    created = rules.create(_payload(), 11)

    with pytest.raises(ExpertRuleValidationError):
        rules.approve(created.rule_id, 1, 12, reason, False)
    assert created.status == "draft" and created.lifecycle_version == 1
    assert len(events) == 1


@pytest.mark.parametrize(
    "reason",
    [
        "Please BEGIN",
        "Please SELECT 1",
        "Please SELECT a + b FROM records",
        "Please CREATE TEMPORARY TABLE scratch (id int)",
        "Please DROP MATERIALIZED VIEW monthly_rollup",
        "Please TRUNCATE records",
        "Please COPY (SELECT 1)",
        "Please SHOW DATABASES",
        "Please DESCRIBE records",
        "Please EXPLAIN SELECT 1",
        "Please ANALYZE records",
        "Please SELECT count(*) FROM records",
        "Please SELECT COALESCE(a, b) FROM records",
        "Please SELECT a::text FROM records",
        "Please CREATE UNIQUE INDEX x ON y(z)",
        "Please SELECT now()",
        "Please SELECT current_user",
        "Please SELECT count(*)",
        "Please SELECT CAST(1 AS text)",
        "Please SELECT pg_sleep(1)",
        "Please DROP IF EXISTS TABLE foo",
        "Please SHOW ALL",
        "Please SHOW search_path",
        "Please VALUES (1)",
        "Please LOAD file",
    ],
)
def test_transition_rejects_prose_prefixed_sql_reason_before_mutation(monkeypatch, reason):
    rules, _, _, _, events = _current_rule_service(monkeypatch)
    created = rules.create(_payload(), 11)

    with pytest.raises(ExpertRuleValidationError):
        rules.approve(created.rule_id, 1, 12, reason, False)
    assert created.status == "draft" and created.lifecycle_version == 1
    assert len(events) == 1


def test_two_sqlite_sessions_allow_only_one_sequential_same_token_transition(monkeypatch):
    rules, _, _, _, events = _current_rule_service(monkeypatch)
    created = rules.create(_payload(), 11)
    rules.approve(created.rule_id, 1, 12, "approved after review", False)
    with pytest.raises(ExpertRuleConflictError):
        rules.approve(created.rule_id, 1, 13, "duplicate approval", False)
    assert [event.event_type for event in events].count("approved") == 1


def test_a_rule_may_have_no_exceptions_but_needs_an_example():
    assert validation.normalize_rule_payload(_payload(exceptions=[]))["exceptions"] == []
    with pytest.raises(ExpertRuleValidationError):
        validation.normalize_rule_payload(_payload(examples=[]))


def test_a_rule_must_build_on_at_least_one_glossary_term():
    from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import srv_expert_rule_link

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(srv_expert_rule_link, "get_dataset", lambda _: object())
    monkeypatch.setattr(srv_expert_rule_link, "glossary_links", lambda _: [])
    with pytest.raises(ExpertRuleValidationError, match="glossary term"):
        srv_expert_rule_link.validate_semantic_links(
            validation.normalize_rule_payload(_payload(glossary_term_ids=[], metric_ids=[]))
        )
    monkeypatch.undo()


def test_a_rule_group_name_is_prose_unique_without_case_and_the_group_id_is_an_integer_or_null():
    assert validation.normalize_group_payload({"name": " Lọc  bản ghi ", "description": ""}) == {
        "name": "Lọc bản ghi",
        "normalized_name": "lọc bản ghi",
        "description": None,
    }
    for payload in (None, {"name": " "}, {"name": "x" * 256}, {"name": "DROP TABLE rules"}, {"name": "A", "x": 1}):
        with pytest.raises(ExpertRuleValidationError):
            validation.normalize_group_payload(payload)
    assert validation.group_id_of({"group_id": None}) is None and validation.group_id_of({"group_id": 2}) == 2
    with pytest.raises(ExpertRuleValidationError):
        validation.group_id_of({"group_id": "2"})


def test_moving_an_approved_rule_keeps_its_revision_and_token_and_audits_the_move(monkeypatch):
    rules, rule_rows, revisions, _, events = _current_rule_service(monkeypatch)
    groups, _ = _current_rule_group_service(rules)
    rules.groups = groups
    filters = groups.create({"name": "Filters"})
    limits = groups.create({"name": "Threshold"})
    created = rules.create(_payload(group_id=filters.id), 11)
    rules.approve(created.rule_id, 1, 12, None, False)
    rule_id = created.rule_id
    assert rule_rows[rule_id].group is filters
    with pytest.raises(ExpertRuleConflictError):
        groups.create({"name": "THRESHOLD"})

    groups.move_rule(rule_id, limits.id, 12)
    groups.move_rule(rule_id, None, 12)

    revision = revisions[created.id]
    assert (revision.status, revision.revision_number, revision.lifecycle_version) == ("approved", 1, 2)
    assert [(event.event_type, event.reason, event.lifecycle_version) for event in events] == [
        ("created", None, 1),
        ("approved", None, 2),
        ("moved", f"Filters {chr(0x2192)} Threshold", 2),
        ("moved", f"Threshold {chr(0x2192)} {group_service.UNGROUPED}", 2),
    ]
    rules.revoke(rule_id, 2, 12, "superseded")
    with pytest.raises(ExpertRuleGroupNotFoundError):
        groups.move_rule(rule_id, 404, 12)
    with pytest.raises(ExpertRuleNotFoundError):
        groups.move_rule(404, None, 12)

def test_an_edit_moves_the_rule_and_a_deleted_group_leaves_its_rules_ungrouped(monkeypatch):
    rules, rule_rows, _, _, events = _current_rule_service(monkeypatch)
    groups, _ = _current_rule_group_service(rules)
    rules.groups = groups
    filters = groups.create({"name": "Filters"})
    created = rules.create(_payload(), 11)
    updated = rules.update(created.rule_id, _payload(group_id=filters.id), 1, 11)
    assert updated.content_hash == created.content_hash
    assert rule_rows[created.rule_id].group_id == filters.id

    renamed = groups.update(filters.id, {"name": "Dimensions"})
    assert groups.delete(renamed.id, 12) == [created.rule_id]
    assert rule_rows[created.rule_id].group_id is None
    moves = [event for event in events if event.event_type == "moved"]
    assert [event.reason for event in moves] == [f"{group_service.UNGROUPED} {chr(0x2192)} Filters", f"Dimensions {chr(0x2192)} {group_service.UNGROUPED}"]
