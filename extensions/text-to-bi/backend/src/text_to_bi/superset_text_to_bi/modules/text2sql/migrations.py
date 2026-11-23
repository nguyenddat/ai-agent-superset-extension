import threading

from flask_appbuilder import Model
from sqlalchemy import text
from superset.extensions import db

from text_to_bi.superset_text_to_bi.common.base_model import TEXT_TO_BI_SCHEMA
from text_to_bi.superset_text_to_bi.modules.conversation.migrations import ensure_conversation_tables
from text_to_bi.superset_text_to_bi.modules.conversation.models import Conversation, ConversationTurn
from text_to_bi.superset_text_to_bi.modules.own_knowledge.migrations import ensure_own_knowledge_tables

from .models import ChatCheckpoint, IngestionJob

MIGRATION_LOCK_KEY = 74_116_341
_ready = False
_lock = threading.Lock()


def ensure_text2sql_tables() -> None:
    global _ready
    # The agent and its index read every knowledge table; own knowledge ensures the chain below it (rules, glossary,
    # metrics, business model).
    ensure_own_knowledge_tables()
    if _ready:
        return
    with _lock:
        if _ready:
            return
        ensure_conversation_tables()
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
        # Import the referenced models so SQLAlchemy can resolve their foreign keys; create only Text2SQL tables.
        _ = Conversation, ConversationTurn
        Model.metadata.create_all(
            bind=connection,
            tables=[ChatCheckpoint.__table__, IngestionJob.__table__],
            checkfirst=True,
        )
