import threading

from flask_appbuilder import Model
from sqlalchemy import text
from superset.extensions import db

from text_to_bi.superset_text_to_bi.common.base_model import TEXT_TO_BI_SCHEMA

from .models import LineageCanvas, LineageEdge

DATA_LINEAGE_MODELS = (LineageEdge, LineageCanvas)
MIGRATION_LOCK_KEY = 74_116_301
_ready = False
_lock = threading.Lock()


def ensure_data_lineage_tables() -> None:
    global _ready
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
            bind=connection, tables=[model.__table__ for model in DATA_LINEAGE_MODELS], checkfirst=True
        )
