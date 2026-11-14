import ast
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect, text

MIGRATION_PATH = Path(__file__).parents[2] / "extensions/semantic-layer/backend/src/text_to_bi/superset_semantic_layer/migrations.py"


def _root_metrics_function(namespace):
    source = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
    function = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "_root_metrics_on_definition")
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(MIGRATION_PATH), "exec"), namespace)  # noqa: S102
    return namespace["_root_metrics_on_definition"]


def test_populated_legacy_metric_migration_keeps_ids_approvals_and_events():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sql_metrics (id INTEGER PRIMARY KEY, metric_name TEXT NOT NULL)"))
        connection.execute(text("CREATE TABLE text_to_bi_metric_definition (id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL, metric_id INTEGER NOT NULL, business_definition TEXT NOT NULL)"))
        connection.execute(text("CREATE TABLE text_to_bi_metric_contract (id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL, metric_id INTEGER NOT NULL, status TEXT NOT NULL, approved_at TEXT, approver_id INTEGER)"))
        connection.execute(text("CREATE TABLE text_to_bi_metric_contract_event (id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL, metric_id INTEGER NOT NULL, action TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO sql_metrics VALUES (10, 'Rain'), (11, 'Wind')"))
        connection.execute(text("INSERT INTO text_to_bi_metric_definition VALUES (40, 3, 10, 'Total rain')"))
        connection.execute(text("INSERT INTO text_to_bi_metric_contract VALUES (50, 3, 10, 'approved', '2026-01-01', 7), (51, 3, 11, 'candidate', NULL, NULL)"))
        connection.execute(text("INSERT INTO text_to_bi_metric_contract_event VALUES (60, 3, 10, 'approve'), (61, 3, 11, 'candidate')"))

    namespace = {
        "db": SimpleNamespace(engine=engine),
        "inspect": inspect,
        "text": text,
        "MetricContract": SimpleNamespace(__tablename__="text_to_bi_metric_contract"),
        "MetricContractEvent": SimpleNamespace(__tablename__="text_to_bi_metric_contract_event"),
        "ReviewStatus": SimpleNamespace(DRAFT=SimpleNamespace(value="draft")),
    }
    migrate = _root_metrics_function(namespace)
    migrate(False)
    migrate(False)

    with engine.connect() as connection:
        definitions = connection.execute(text("SELECT id, dataset_id, metric_id, business_definition FROM text_to_bi_metric_definition ORDER BY metric_id")).all()
        contracts = connection.execute(text("SELECT id, definition_id, status, approved_at, approver_id FROM text_to_bi_metric_contract ORDER BY id")).all()
        events = connection.execute(text("SELECT id, definition_id, metric_id, metric_name, action FROM text_to_bi_metric_contract_event ORDER BY id")).all()
    assert definitions == [(40, 3, 10, "Total rain"), (41, 3, 11, "Chưa có định nghĩa nghiệp vụ.")]
    assert contracts == [(50, 40, "approved", "2026-01-01", 7), (51, 41, "draft", None, None)]
    assert events == [(60, 40, 10, "Rain", "approve"), (61, 41, 11, "Wind", "candidate")]


def test_postgres_legacy_history_foreign_keys_are_removed_once():
    statements = []
    foreign_keys = [
        {"name": "event_dataset_id_fkey", "constrained_columns": ["dataset_id"]},
        {"name": "event_metric_id_fkey", "constrained_columns": ["metric_id"]},
        {"name": "event_actor_id_fkey", "constrained_columns": ["actor_id"]},
    ]
    nullable = {"dataset_id": False, "metric_id": False}

    class Connection:
        dialect = SimpleNamespace(identifier_preparer=SimpleNamespace(quote=lambda name: f'"{name}"'))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, *_args):
            sql = str(statement)
            statements.append(sql)
            if "DROP CONSTRAINT" in sql:
                foreign_keys[:] = [key for key in foreign_keys if f'"{key["name"]}"' not in sql]
            if "DROP NOT NULL" in sql:
                nullable[sql.split("ALTER COLUMN ")[1].split()[0]] = True

    def inspect_connection(_connection):
        def columns(table):
            if table == "text_to_bi_metric_contract":
                return [{"name": "definition_id"}]
            return [{"name": "metric_name"}, *({"name": name, "nullable": value} for name, value in nullable.items())]

        return SimpleNamespace(get_columns=columns, get_foreign_keys=lambda _table: list(foreign_keys))

    namespace = {
        "db": SimpleNamespace(engine=SimpleNamespace(begin=Connection)),
        "inspect": inspect_connection,
        "text": text,
        "MetricContract": SimpleNamespace(__tablename__="text_to_bi_metric_contract"),
        "MetricContractEvent": SimpleNamespace(__tablename__="text_to_bi_metric_contract_event"),
    }
    migrate = _root_metrics_function(namespace)
    migrate(True)
    migrate(True)

    assert statements == [
        'ALTER TABLE text_to_bi_metric_contract_event DROP CONSTRAINT "event_dataset_id_fkey"',
        'ALTER TABLE text_to_bi_metric_contract_event DROP CONSTRAINT "event_metric_id_fkey"',
        "ALTER TABLE text_to_bi_metric_contract_event ALTER COLUMN dataset_id DROP NOT NULL",
        "ALTER TABLE text_to_bi_metric_contract_event ALTER COLUMN metric_id DROP NOT NULL",
    ]
    assert [key["name"] for key in foreign_keys] == ["event_actor_id_fkey"]
