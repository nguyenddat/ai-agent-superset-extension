import threading

from flask_appbuilder import Model
from sqlalchemy import text
from superset.extensions import db

from text_to_bi.superset_text_to_bi.common.base_model import TEXT_TO_BI_SCHEMA
from text_to_bi.superset_text_to_bi.modules.data_dictionary.migrations import ensure_data_dictionary_tables

from .models import BusinessCanvas, BusinessDomain, DataLayer, DatasetLayer, business_domain_tables

BUSINESS_MODEL_TABLES = (
    BusinessCanvas.__table__,
    BusinessDomain.__table__,
    DataLayer.__table__,
    DatasetLayer.__table__,
    business_domain_tables,
)
MIGRATION_LOCK_KEY = 74_116_301
_ready = False
_lock = threading.Lock()

def ensure_business_model_tables() -> None:
    global _ready
    ensure_data_dictionary_tables()
    if _ready:
        return
    with _lock:
        if _ready:
            return
        if db.engine.dialect.name != "postgresql":
            _migrate()
        else:
            with db.engine.connect() as lock_connection:
                lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
                try:
                    _migrate()
                finally:
                    lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
                    )
        _ready = True
    # These domain association tables are owned by their respective modules.
    # Re-run their idempotent ensure functions after BusinessDomain is registered
    # so startup order cannot leave the tables missing.
    from text_to_bi.superset_text_to_bi.modules.expert_rule_management.migrations import (
        ensure_expert_rule_tables,
    )

    ensure_expert_rule_tables()

def _migrate() -> None:
    with db.engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TEXT_TO_BI_SCHEMA}"))
        Model.metadata.create_all(
            bind=connection, tables=list(BUSINESS_MODEL_TABLES), checkfirst=True
        )
