import threading

from flask_appbuilder import Model
from sqlalchemy import inspect, text
from superset.extensions import db

from text_to_bi.superset_text_to_bi.common.base_model import TEXT_TO_BI_SCHEMA
from text_to_bi.superset_text_to_bi.modules.glossary_management.migrations import ensure_glossary_tables

from .models import (
    ExpertRule,
    ExpertRuleGlossaryLink,
    ExpertRuleMetricLink,
    ExpertRuleRevision,
    expert_rule_domains,
)

MIGRATION_LOCK_KEY = 74_116_301
_ready = False
_lock = threading.Lock()


def ensure_expert_rule_tables() -> None:
    global _ready
    ensure_glossary_tables()
    if _ready:
        _ensure_domain_association()
        return
    with _lock:
        if _ready:
            return
        if db.engine.dialect.name != "postgresql":
            _migrate()
        else:
            with db.engine.connect() as connection:
                connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
                try:
                    _migrate()
                finally:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
        _ready = True
        _ensure_domain_association()


def _ensure_domain_association() -> None:
    if f"{TEXT_TO_BI_SCHEMA}.business_domains" not in Model.metadata.tables:
        return
    with db.engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TEXT_TO_BI_SCHEMA}"))
        if not inspect(connection).has_table("expert_rule_domains", schema=TEXT_TO_BI_SCHEMA):
            Model.metadata.create_all(bind=connection, tables=[expert_rule_domains], checkfirst=True)


def _migrate() -> None:
    with db.engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TEXT_TO_BI_SCHEMA}"))
        tables = [
            ExpertRule.__table__,
            ExpertRuleRevision.__table__,
            ExpertRuleGlossaryLink.__table__,
            ExpertRuleMetricLink.__table__,
        ]
        if f"{TEXT_TO_BI_SCHEMA}.business_domains" in Model.metadata.tables:
            tables.append(expert_rule_domains)
        Model.metadata.create_all(bind=connection, tables=tables, checkfirst=True)
