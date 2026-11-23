import threading

from flask_appbuilder import Model
from sqlalchemy import text
from superset.extensions import db

from text_to_bi.superset_text_to_bi.common.base_model import TEXT_TO_BI_SCHEMA
from text_to_bi.superset_text_to_bi.modules.business_model.migrations import ensure_business_model_tables

from .models import Metric, metric_domains

MIGRATION_LOCK_KEY = 74_116_301
_ready = False
_lock = threading.Lock()


def ensure_metric_tables() -> None:
    global _ready
    # metric_domains references business_domains, so its owner creates that table first. Called before taking
    # _lock: the business model's first run re-enters this function through the expert rule chain.
    ensure_business_model_tables()
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
        Model.metadata.create_all(bind=connection, tables=[Metric.__table__, metric_domains], checkfirst=True)
        if connection.dialect.name == "postgresql":
            # Tables created before the review workflow have no status column.
            connection.execute(text(
                f"ALTER TABLE {TEXT_TO_BI_SCHEMA}.metrics ADD COLUMN IF NOT EXISTS status "
                "VARCHAR(16) NOT NULL DEFAULT 'draft'"
            ))
