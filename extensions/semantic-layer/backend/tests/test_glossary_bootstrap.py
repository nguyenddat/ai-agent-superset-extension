from types import SimpleNamespace

from catalog_source import compile_into, module_function
from sqlalchemy import create_engine, text


def test_glossary_bootstrap_creates_parent_tables_before_children_with_checkfirst():
    namespace = compile_into(_migration_namespace(), module_function("_migrate_dictionary_tables"))

    namespace["_migrate_dictionary_tables"]()
    namespace["_migrate_dictionary_tables"]()

    glossary_calls = [call for call in namespace["calls"] if call[0].startswith("Glossary")]
    assert [name for name, _ in glossary_calls] == [
        "GlossaryTermGroup",
        "GlossaryTerm",
        "GlossaryTermRevision",
        "GlossaryTermLink",
        "GlossaryTermAuditEvent",
    ] * 2
    assert all(checkfirst for _, checkfirst in glossary_calls)


def test_expert_rule_bootstrap_creates_parent_tables_before_children_with_checkfirst():
    namespace = compile_into(_migration_namespace(), module_function("_migrate_dictionary_tables"))

    namespace["_migrate_dictionary_tables"]()

    expert_calls = [call for call in namespace["calls"] if call[0].startswith("ExpertRule")]
    assert [name for name, _ in expert_calls] == [
        "ExpertRuleGroup",
        "ExpertRule",
        "ExpertRuleRevision",
        "ExpertRuleLink",
        "ExpertRuleAuditEvent",
    ]
    assert all(checkfirst for _, checkfirst in expert_calls)


def _migration_namespace():
    calls = []

    class Table:
        def __init__(self, name):
            self.name = name

        def create(self, *, bind, checkfirst):
            calls.append((self.name, checkfirst))

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return SimpleNamespace(scalars=list, all=list)

    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"), begin=lambda: Connection())
    db = SimpleNamespace(engine=engine)
    inspect = lambda _engine: SimpleNamespace(
        get_columns=lambda _name: [],
        get_indexes=lambda _name: [],
        has_table=lambda _name: False,
    )
    names = (
        "DataLayer",
        "DatasetDictionary",
        "ColumnDictionary",
        "DatasetGrain",
        "ColumnTransformation",
        "ColumnTransformationSource",
        "BusinessDomain",
        "LineageEdge",
        "BusinessCanvas",
        "LineageCanvas",
        "MetricContract",
        "MetricContractEvent",
        "MetricDefinition",
        "RelationshipContract",
        "GlossaryTermGroup",
        "GlossaryTerm",
        "GlossaryTermRevision",
        "GlossaryTermLink",
        "GlossaryTermAuditEvent",
        "ExpertRuleGroup",
        "ExpertRule",
        "ExpertRuleRevision",
        "ExpertRuleLink",
        "ExpertRuleAuditEvent",
        "TextEmbedding",
        "GroupSuggestionDismissal",
        "DatasetProposal",
        "Contradiction",
        "ContradictionJudgement",
    )
    namespace = {name: SimpleNamespace(__tablename__=name, __table__=Table(name)) for name in names}
    namespace.update(
        db=db,
        inspect=inspect,
        text=lambda value: value,
        business_domain_dataset=Table("business_domain_dataset"),
        calls=calls,
        _add_group_columns=lambda postgres: calls.append(("_add_group_columns", postgres)),
        _sync_rule_name_keys=lambda: calls.append(("_sync_rule_name_keys", None)),
        _root_metrics_on_definition=lambda postgres: calls.append(("_root_metrics_on_definition", postgres)),
    )
    return namespace


def _group_column_namespace(columns, check_constraints):
    statements = []

    class Connection:
        dialect = SimpleNamespace(identifier_preparer=SimpleNamespace(quote=lambda name: f'"{name}"'))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, *_args):
            statements.append(statement)

    inspector = SimpleNamespace(
        get_columns=lambda table: [{"name": name} for name in columns.get(table, [])],
        get_check_constraints=lambda table: check_constraints.get(table, []),
        get_foreign_keys=lambda _table: [],
    )
    namespace = {
        name: SimpleNamespace(__tablename__=table)
        for name, table in (
            ("GlossaryTerm", "text_to_bi_glossary_term"),
            ("GlossaryTermGroup", "text_to_bi_glossary_term_group"),
            ("GlossaryTermAuditEvent", "text_to_bi_glossary_term_audit_event"),
            ("ExpertRule", "text_to_bi_expert_rule"),
            ("ExpertRuleGroup", "text_to_bi_expert_rule_group"),
            ("ExpertRuleAuditEvent", "text_to_bi_expert_rule_audit_event"),
        )
    }
    namespace.update(
        db=SimpleNamespace(engine=SimpleNamespace(begin=Connection)),
        inspect=lambda _connection: inspector,
        text=lambda value: value,
        GLOSSARY_AUDIT_EVENT_TYPES="event_type IN ('created', 'moved')",
        EXPERT_RULE_AUDIT_EVENT_TYPES="event_type IN ('created', 'moved')",
    )
    compile_into(namespace, module_function("_add_group_columns"))
    return namespace["_add_group_columns"], statements


def test_terms_and_rules_created_before_groups_get_an_indexed_group_column_once():
    add_group_columns, statements = _group_column_namespace({}, {})
    add_group_columns(False)
    assert statements == [
        "ALTER TABLE text_to_bi_glossary_term ADD COLUMN group_id INTEGER",
        "CREATE INDEX ix_text_to_bi_glossary_term_group_id ON text_to_bi_glossary_term (group_id)",
        "ALTER TABLE text_to_bi_expert_rule ADD COLUMN group_id INTEGER",
        "CREATE INDEX ix_text_to_bi_expert_rule_group_id ON text_to_bi_expert_rule (group_id)",
    ]

    columns = {"text_to_bi_glossary_term": ["group_id"], "text_to_bi_expert_rule": ["group_id"]}
    add_group_columns, statements = _group_column_namespace(columns, {})
    add_group_columns(False)
    assert statements == []


def test_postgres_audit_trails_created_before_groups_learn_to_record_moves():
    old_check = {"name": "ck_old", "sqltext": "event_type IN ('created', 'updated', 'approved', 'revoked')"}
    new_check = {"name": "ck_new", "sqltext": "event_type IN ('created', 'moved')"}
    columns = {"text_to_bi_glossary_term": ["group_id"], "text_to_bi_expert_rule": ["group_id"]}
    checks = {"text_to_bi_glossary_term_audit_event": [old_check], "text_to_bi_expert_rule_audit_event": [new_check]}
    add_group_columns, statements = _group_column_namespace(columns, checks)
    add_group_columns(True)
    assert statements == [
        'ALTER TABLE text_to_bi_glossary_term_audit_event DROP CONSTRAINT "ck_old"',
        (
            "ALTER TABLE text_to_bi_glossary_term_audit_event ADD CONSTRAINT ck_text_to_bi_glossary_audit_event "
            "CHECK (event_type IN ('created', 'moved'))"
        ),
    ]


def test_rules_renamed_before_renames_moved_the_name_key_get_the_key_of_their_current_name():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE rule (id INTEGER PRIMARY KEY, normalized_name TEXT UNIQUE)"))
        connection.execute(
            text("CREATE TABLE revision (id INTEGER PRIMARY KEY, rule_id INTEGER, name TEXT, is_current BOOLEAN)")
        )
        connection.execute(text("INSERT INTO rule VALUES (1, 'hot day'), (2, 'wet day'), (3, 'cold day')"))
        connection.execute(
            text(
                "INSERT INTO revision VALUES (1, 1, 'Hot day', 0), (2, 1, 'Very  Hot day', 1), "
                "(3, 2, 'Wet day', 1), (4, 3, 'Wet day', 1)"
            )
        )
    namespace = {
        "db": SimpleNamespace(engine=engine),
        "text": text,
        "ExpertRule": SimpleNamespace(__tablename__="rule"),
        "ExpertRuleRevision": SimpleNamespace(__tablename__="revision"),
    }
    compile_into(namespace, module_function("_sync_rule_name_keys"))

    namespace["_sync_rule_name_keys"]()

    with engine.connect() as connection:
        name_keys = dict(connection.execute(text("SELECT id, normalized_name FROM rule")).all())
    # Rule 3 was renamed onto rule 2's name before renames were checked, so it keeps its old key.
    assert name_keys == {1: "very hot day", 2: "wet day", 3: "cold day"}
