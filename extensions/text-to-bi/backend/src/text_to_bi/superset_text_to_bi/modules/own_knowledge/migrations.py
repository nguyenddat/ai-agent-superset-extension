import threading

from flask_appbuilder import Model
from sqlalchemy import text
from superset.extensions import db

from text_to_bi.superset_text_to_bi.common.base_model import TEXT_TO_BI_SCHEMA
from text_to_bi.superset_text_to_bi.modules.expert_rule_management.migrations import ensure_expert_rule_tables

from .models import OwnClarification, OwnKnowledgeEntry, OwnProposal

MIGRATION_LOCK_KEY = 74_116_311
_ready = False
_lock = threading.Lock()


def ensure_own_knowledge_tables() -> None:
    global _ready
    ensure_expert_rule_tables()
    if _ready:
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


def _migrate() -> None:
    with db.engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TEXT_TO_BI_SCHEMA}"))
        Model.metadata.create_all(
            bind=connection,
            tables=[OwnClarification.__table__, OwnProposal.__table__, OwnKnowledgeEntry.__table__],
            checkfirst=True,
        )
