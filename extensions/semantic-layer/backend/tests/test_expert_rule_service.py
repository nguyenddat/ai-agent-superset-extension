import inspect
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from text_to_bi.superset_semantic_layer.modules.expert_rules.exceptions import (
    ExpertRuleGroupNotFoundError,
    ExpertRuleNotFoundError,
)
from text_to_bi.superset_semantic_layer.modules.expert_rules.services import expert_rule as service
from text_to_bi.superset_semantic_layer.modules.expert_rules.services import expert_rule_group as group_service


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
    normalized = service.normalize_rule_payload(_payload())
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
    normalized = service.normalize_rule_payload(_payload(), column)
    assert normalized["schema_version"] == 2
    assert normalized["conditions"][0]["field_ref"]["column_dictionary_id"] == 70
    legacy = _payload(
        schema_version=1, conditions=[{"field": "observation_status", "operator": "equals", "value": "final"}]
    )
    assert service.normalize_rule_payload(legacy, column)["conditions"] == normalized["conditions"]
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(
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
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(
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
    normalized = service.normalize_rule_payload(_payload(exceptions=[{"when": text, "outcome": "review manually"}]))
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
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(payload)


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
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(_payload(exceptions=[{"when": command, "outcome": "ignore"}]))


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
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(_payload(exceptions=[{"when": text, "outcome": "ignore"}]))


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
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(_payload(examples=[{"question": command, "intent": "aggregate"}]))


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
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(_payload(exceptions=[{"when": f"Please {command}", "outcome": "ignore"}]))


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
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(_payload(exceptions=[{"when": f"Please {command}", "outcome": "ignore"}]))


@pytest.mark.parametrize("command", ["SHOW ALL", "LOAD file"])
def test_normalize_payload_rejects_dialect_commands_without_optional_parser(command):
    """Dialect commands are unsafe without an optional parser runtime dependency."""
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(_payload(exceptions=[{"when": f"Please {command}", "outcome": "ignore"}]))


def test_normalize_payload_constrains_condition_operator_to_enum():
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(
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
    assert service.normalize_rule_payload(payload)


def test_validate_links_requires_approved_same_dataset_objects():
    payload = service.normalize_rule_payload(_payload())
    resolver = lambda dataset_id: SimpleNamespace(id=dataset_id) if dataset_id == 7 else None
    glossary = lambda term_id: (
        SimpleNamespace(status="approved", is_current=True, dataset_id=7) if term_id == 3 else None
    )
    metric = lambda metric_id: (
        SimpleNamespace(id=metric_id, dataset_id=7, status="approved", is_current=True) if metric_id == 9 else None
    )
    service.validate_semantic_links(payload, resolver, glossary, metric)

    with pytest.raises(service.ExpertRuleValidationError):
        service.validate_semantic_links(payload, resolver, lambda _: None, metric)
    with pytest.raises(service.ExpertRuleValidationError):
        service.validate_semantic_links(
            payload, resolver, glossary, lambda _: SimpleNamespace(dataset_id=8, status="approved", is_current=True)
        )


def test_validate_links_selects_a_matching_current_glossary_link_from_multiple_links():
    payload = service.normalize_rule_payload(_payload())
    resolver = lambda dataset_id: SimpleNamespace(id=dataset_id) if dataset_id == 7 else None
    glossary = lambda _: [
        SimpleNamespace(status="approved", is_current=True, dataset_id=2),
        SimpleNamespace(status="approved", is_current=True, dataset_id=7),
    ]
    metric = lambda _: SimpleNamespace(id=9, dataset_id=7, status="approved", is_current=True)
    service.validate_semantic_links(payload, resolver, glossary, metric)

    with pytest.raises(service.ExpertRuleValidationError):
        service.validate_semantic_links(payload, resolver, lambda _: glossary(3)[:1], metric)


def test_discoverability_needs_approved_current_and_live_links():
    rule = SimpleNamespace(status="approved", is_current=True)
    links = [SimpleNamespace(fingerprint="live", dataset_id=7)]
    assert service.rule_is_discoverable(rule, links, lambda _: "live")
    rule.status = "revoked"
    assert not service.rule_is_discoverable(rule, links, lambda _: "live")
    rule.status = "approved"
    assert not service.rule_is_discoverable(rule, links, lambda _: "changed")


def test_mutations_use_row_lock_and_expected_revision():
    repositories = Path(service.__file__).parents[1] / "repositories"
    for repository in ("expert_rule.py", "expert_rule_revision.py"):
        assert "with_for_update()" in (repositories / repository).read_text(encoding="utf-8")
    assert ".lock(" in inspect.getsource(service._lock) and "lock_current(" in inspect.getsource(service._lock)
    for name in ("update_draft", "approve_rule", "revoke_rule"):
        assert "expected_revision" in inspect.getsource(getattr(service, name))


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
    module = types.ModuleType("text_to_bi.superset_semantic_layer.modules.expert_rules.models")
    module.ExpertRule, module.ExpertRuleRevision = Rule, Revision
    module.ExpertRuleLink, module.ExpertRuleAuditEvent, module.ExpertRuleGroup = Link, Audit, Group
    monkeypatch.setitem(sys.modules, module.__name__, module)
    # A repository binds its model when imported, so import the repositories again with these tables.
    for name in [name for name in sys.modules if name.startswith(f"{service.__package__[:-9]}.repositories.")]:
        monkeypatch.delitem(sys.modules, name)
    return sessionmaker(bind=engine)(), Rule, Revision, Audit


def test_sqlite_lifecycle_create_update_approve_revoke_audit_conflict_and_rollback(monkeypatch):
    session, rule_model, revision_model, audit_model = _lifecycle_session(monkeypatch)
    dataset = lambda key: SimpleNamespace(id=key) if key == 7 else None
    glossary = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 3 else None
    metric = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 9 else None
    fingerprint = lambda kind, target_id, dataset_id: f"{kind}:{target_id}:{dataset_id}"

    created = service.create_draft(session, _payload(), 11, dataset, glossary, metric, fingerprint)
    session.commit()
    assert created.revision_number == created.lifecycle_version == 1
    with pytest.raises(service.ExpertRuleConflictError):
        service.create_draft(session, _payload(), 11, dataset, glossary, metric, fingerprint)
    session.rollback()
    assert session.query(rule_model).count() == 1

    updated = service.update_draft(
        session, created, _payload(name="Exclude provisional records"), 1, 12, dataset, glossary, metric, fingerprint
    )
    session.commit()
    assert updated.revision_number == updated.lifecycle_version == 2
    assert session.query(revision_model).filter_by(revision_number=1).one().is_current is False
    with pytest.raises(service.ExpertRuleConflictError):
        service.update_draft(session, updated, _payload(name="new"), 1, 12, dataset, glossary, metric, fingerprint)
    session.rollback()

    # A second caller that retained the create token cannot approve the update.
    with pytest.raises(service.ExpertRuleConflictError):
        service.approve_rule(session, updated, 1, 13)
    session.rollback()
    service.approve_rule(session, updated, 2, 13)
    session.commit()
    assert updated.status == "approved" and updated.lifecycle_version == 3
    with pytest.raises(service.ExpertRuleConflictError):
        service.revoke_rule(session, updated, 2, 14, "superseded")
    session.rollback()
    service.revoke_rule(session, updated, 3, 14, "superseded")
    session.commit()
    # A revoked rule stays current so it can be corrected and reviewed again; discovery skips it by status.
    assert updated.status == "revoked" and updated.is_current is True and updated.lifecycle_version == 4
    assert [event.event_type for event in session.query(audit_model).order_by(audit_model.id)] == [
        "created",
        "updated",
        "approved",
        "revoked",
    ]
    assert [event.lifecycle_version for event in session.query(audit_model).order_by(audit_model.id)] == [1, 2, 3, 4]


def _lifecycle_resolvers():
    dataset = lambda key: SimpleNamespace(id=key) if key == 7 else None
    glossary = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 3 else None
    metric = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 9 else None
    fingerprint = lambda kind, target_id, dataset_id: f"{kind}:{target_id}:{dataset_id}"
    return dataset, glossary, metric, fingerprint


def test_the_author_may_approve_unless_a_second_reviewer_is_required(monkeypatch):
    session, _, _, _ = _lifecycle_session(monkeypatch)
    resolvers = _lifecycle_resolvers()
    created = service.create_draft(session, _payload(), 11, *resolvers)
    session.commit()
    with pytest.raises(service.ExpertRuleSelfApprovalError):
        service.approve_rule(session, created, 1, 11, require_second_reviewer=True)
    session.rollback()

    # Whoever edited the latest revision is its author, even if someone else created the rule.
    updated = service.update_draft(session, created, _payload(name="Exclude draft observations"), 1, 12, *resolvers)
    session.commit()
    assert service.revision_author_id(session, updated) == 12
    with pytest.raises(service.ExpertRuleSelfApprovalError):
        service.approve_rule(session, updated, 2, 12, require_second_reviewer=True)
    session.rollback()
    service.approve_rule(session, updated, 2, 11, require_second_reviewer=True)
    session.commit()
    assert updated.status == "approved" and updated.approver_id == 11


def test_a_rename_moves_the_rule_name_key_and_refuses_another_rules_name(monkeypatch):
    session, rule_model, _, _ = _lifecycle_session(monkeypatch)
    resolvers = _lifecycle_resolvers()
    created = service.create_draft(session, _payload(), 11, *resolvers)
    other = service.create_draft(session, _payload(name="Exclude test stations"), 11, *resolvers)
    session.commit()

    service.update_draft(session, created, _payload(name="Exclude  Provisional rows"), 1, 11, *resolvers)
    session.commit()
    assert session.get(rule_model, created.rule_id).normalized_name == "exclude provisional rows"
    # The old name is free again.
    service.create_draft(session, _payload(), 11, *resolvers)
    session.commit()

    with pytest.raises(service.ExpertRuleConflictError):
        service.update_draft(session, other, _payload(name="exclude provisional rows"), 1, 11, *resolvers)
    session.rollback()
    assert session.get(rule_model, other.rule_id).normalized_name == "exclude test stations"


def test_a_single_administrator_approves_their_own_draft_by_default(monkeypatch):
    session, _, _, _ = _lifecycle_session(monkeypatch)
    created = service.create_draft(session, _payload(), 11, *_lifecycle_resolvers())
    session.commit()
    service.approve_rule(session, created, 1, 11)
    assert created.status == "approved" and created.approver_id == 11


def test_a_revoked_rule_can_be_corrected_into_a_new_draft(monkeypatch):
    session, _, revision_model, _ = _lifecycle_session(monkeypatch)
    resolvers = _lifecycle_resolvers()
    created = service.create_draft(session, _payload(), 11, *resolvers)
    session.commit()
    service.approve_rule(session, created, 1, 12)
    service.revoke_rule(session, created, 2, 12, "Ngưỡng không còn đúng")
    session.commit()

    corrected = service.update_draft(session, created, _payload(name="Exclude provisional rows"), 3, 11, *resolvers)
    session.commit()
    assert corrected.status == "draft" and corrected.revision_number == 2 and corrected.lifecycle_version == 4
    assert session.query(revision_model).filter_by(is_current=True).one().id == corrected.id


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
    session, _, _, audit_model = _lifecycle_session(monkeypatch)
    dataset = lambda key: SimpleNamespace(id=key) if key == 7 else None
    glossary = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 3 else None
    metric = lambda key: SimpleNamespace(id=key, status="approved", is_current=True, dataset_id=7) if key == 9 else None
    fingerprint = lambda kind, target_id, dataset_id: f"{kind}:{target_id}:{dataset_id}"
    created = service.create_draft(session, _payload(), 11, dataset, glossary, metric, fingerprint)
    session.commit()

    with pytest.raises(service.ExpertRuleValidationError):
        service.approve_rule(session, created, 1, 12, reason)
    assert created.status == "draft" and created.lifecycle_version == 1
    assert session.query(audit_model).count() == 1


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
    session, _, _, audit_model = _lifecycle_session(monkeypatch)
    dataset = lambda key: SimpleNamespace(id=key) if key == 7 else None
    glossary = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 3 else None
    metric = lambda key: SimpleNamespace(id=key, status="approved", is_current=True, dataset_id=7) if key == 9 else None
    fingerprint = lambda kind, target_id, dataset_id: f"{kind}:{target_id}:{dataset_id}"
    created = service.create_draft(session, _payload(), 11, dataset, glossary, metric, fingerprint)
    session.commit()

    with pytest.raises(service.ExpertRuleValidationError):
        service.approve_rule(session, created, 1, 12, reason)
    assert created.status == "draft" and created.lifecycle_version == 1
    assert session.query(audit_model).count() == 1


def test_two_sqlite_sessions_allow_only_one_sequential_same_token_transition(monkeypatch):
    """SQLite ignores FOR UPDATE; this verifies stale-token behavior, not DB lock contention."""
    session_one, _, revision_model, audit_model = _lifecycle_session(monkeypatch)
    factory = sessionmaker(bind=session_one.bind)
    dataset = lambda key: SimpleNamespace(id=key) if key == 7 else None
    glossary = lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 3 else None
    metric = lambda key: SimpleNamespace(id=key, status="approved", is_current=True, dataset_id=7) if key == 9 else None
    fingerprint = lambda kind, target_id, dataset_id: f"{kind}:{target_id}:{dataset_id}"
    created = service.create_draft(session_one, _payload(), 11, dataset, glossary, metric, fingerprint)
    session_one.commit()
    session_two = factory()
    first = session_one.query(revision_model).filter_by(id=created.id).one()
    second = session_two.query(revision_model).filter_by(id=created.id).one()

    service.approve_rule(session_one, first, 1, 12, "approved after review")
    session_one.commit()
    with pytest.raises(service.ExpertRuleConflictError):
        service.approve_rule(session_two, second, 1, 13, "duplicate approval")
    session_two.rollback()
    assert session_one.query(audit_model).filter_by(event_type="approved").count() == 1


def test_a_rule_may_have_no_exceptions_but_needs_an_example():
    assert service.normalize_rule_payload(_payload(exceptions=[]))["exceptions"] == []
    with pytest.raises(service.ExpertRuleValidationError):
        service.normalize_rule_payload(_payload(examples=[]))


def test_a_rule_must_build_on_at_least_one_glossary_term():
    with pytest.raises(service.ExpertRuleValidationError, match="glossary term"):
        service.validate_semantic_links(
            service.normalize_rule_payload(_payload(glossary_term_ids=[], metric_ids=[])),
            lambda _: object(),
            lambda _: None,
            lambda _: None,
        )


def test_a_rule_group_name_is_prose_unique_without_case_and_the_group_id_is_an_integer_or_null():
    assert group_service.normalize_group_payload({"name": " Lọc  bản ghi ", "description": ""}) == {
        "name": "Lọc bản ghi",
        "normalized_name": "lọc bản ghi",
        "description": None,
    }
    for payload in (None, {"name": " "}, {"name": "x" * 256}, {"name": "DROP TABLE rules"}, {"name": "A", "x": 1}):
        with pytest.raises(service.ExpertRuleValidationError):
            group_service.normalize_group_payload(payload)
    assert group_service.rule_group_id({"group_id": None}) is None and group_service.rule_group_id({"group_id": 2}) == 2
    with pytest.raises(service.ExpertRuleValidationError, match="Nhóm rule không hợp lệ"):
        group_service.rule_group_id({"group_id": "2"})


def test_moving_an_approved_rule_keeps_its_revision_and_token_and_audits_the_move(monkeypatch):
    session, rule_model, revision_model, audit_model = _lifecycle_session(monkeypatch)
    resolvers = _lifecycle_resolvers()
    filters = group_service.create_rule_group(session, {"name": "Lọc bản ghi", "description": "Loại bản ghi tạm"})
    limits = group_service.create_rule_group(session, {"name": "Ngưỡng"})
    created = service.create_draft(session, _payload(group_id=filters.id), 11, *resolvers)
    service.approve_rule(session, created, 1, 12)
    session.commit()
    rule_id = created.rule_id
    assert session.get(rule_model, rule_id).group_id == filters.id
    with pytest.raises(service.ExpertRuleConflictError, match="cùng tên"):
        group_service.create_rule_group(session, {"name": "ngưỡng"})
    session.rollback()

    group_service.move_rule(session, rule_id, limits.id, 12)
    group_service.move_rule(session, rule_id, None, 12)
    session.commit()

    revision = session.query(revision_model).one()
    assert (revision.status, revision.revision_number, revision.lifecycle_version) == ("approved", 1, 2)
    events = session.query(audit_model).order_by(audit_model.id).all()
    assert [(event.event_type, event.reason, event.lifecycle_version) for event in events] == [
        ("created", None, 1),
        ("approved", None, 2),
        ("moved", "Lọc bản ghi → Ngưỡng", 2),
        ("moved", "Ngưỡng → Chưa phân nhóm", 2),
    ]
    # The move did not touch the lifecycle version, so a client still holding it can revoke.
    service.revoke_rule(session, revision, 2, 12, "superseded")
    with pytest.raises(ExpertRuleGroupNotFoundError):
        group_service.move_rule(session, rule_id, 404, 12)
    with pytest.raises(ExpertRuleNotFoundError):
        group_service.move_rule(session, 404, None, 12)


def test_an_edit_moves_the_rule_and_a_deleted_group_leaves_its_rules_ungrouped(monkeypatch):
    session, rule_model, _, audit_model = _lifecycle_session(monkeypatch)
    resolvers = _lifecycle_resolvers()
    filters = group_service.create_rule_group(session, {"name": "Lọc bản ghi"})
    created = service.create_draft(session, _payload(), 11, *resolvers)
    session.commit()
    updated = service.update_draft(session, created, _payload(group_id=filters.id), 1, 11, *resolvers)
    session.commit()
    assert updated.content_hash == created.content_hash
    assert session.get(rule_model, created.rule_id).group_id == filters.id

    renamed = group_service.update_rule_group(session, filters.id, {"name": "Lọc dữ liệu"})
    assert group_service.delete_rule_group(session, renamed.id, 12) == [created.rule_id]
    session.commit()
    assert session.get(rule_model, created.rule_id).group_id is None
    moves = session.query(audit_model).filter_by(event_type="moved").order_by(audit_model.id)
    assert [event.reason for event in moves] == ["Chưa phân nhóm → Lọc bản ghi", "Lọc dữ liệu → Chưa phân nhóm"]
