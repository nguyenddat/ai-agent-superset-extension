import logging
import threading
import time

from flask_appbuilder import Model
from sqlalchemy import text
from superset.extensions import db

from .common.base_model import TEXT_TO_BI_SCHEMA
from .modules.data_dictionary.models import (
    ColumnAggregation,
    ColumnDictionary,
    ColumnSynonym,
    IndicatorAggregation,
    TableColumnRole,
    TableDictionary,
    TableTimeGrain,
)
from .modules.expert_rule_management.models import (
    ExpertRule,
    ExpertRuleGlossaryLink,
    ExpertRuleMetricLink,
    ExpertRuleRevision,
    expert_rule_domains,
)
from .modules.glossary_management.models import GlossaryLink, GlossaryRevision, GlossaryTerm, glossary_term_domains
from .modules.metric_management.models import Metric, metric_domains

logger = logging.getLogger(__name__)

# Every table of the extension; create_all orders them by their foreign keys.
EXTENSION_MODELS = (
    TableDictionary, TableColumnRole, TableTimeGrain, IndicatorAggregation, ColumnDictionary, ColumnAggregation,
    ColumnSynonym, Metric, GlossaryTerm, GlossaryRevision, GlossaryLink, ExpertRule, ExpertRuleRevision,
    ExpertRuleGlossaryLink, ExpertRuleMetricLink,
)

# Arbitrary key shared by every Superset worker so only one of them migrates at a time.
MIGRATION_LOCK_KEY = 74_116_301
MIGRATION_RETRY_SECONDS = 30

_tables_ready = False
_migration_failed_at: float | None = None
_tables_lock = threading.Lock()


# Creates the schema, the tables and the roles once per process; routes call it before touching the tables.
def ensure_tables() -> None:
    global _tables_ready, _migration_failed_at
    if _tables_ready:
        return
    with _tables_lock:
        if _tables_ready:
            return
        # A failing migration holds ACCESS EXCLUSIVE locks while it runs, so requests must not retry it back to back.
        failed_at = _migration_failed_at
        if failed_at is not None and time.monotonic() - failed_at < MIGRATION_RETRY_SECONDS:
            raise RuntimeError("The Text to BI table migration failed recently; see the earlier error in the log.")
        try:
            if db.engine.dialect.name != "postgresql":
                _migrate()
            else:
                with db.engine.connect() as lock_connection:
                    lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
                    try:
                        _migrate()
                    finally:
                        lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
        except Exception:
            _migration_failed_at = time.monotonic()
            logger.exception("Text to BI migration failed; next attempt in %ss", MIGRATION_RETRY_SECONDS)
            raise
        _migration_failed_at = None
        _tables_ready = True


def _migrate() -> None:
    with db.engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TEXT_TO_BI_SCHEMA}"))
        tables = [model.__table__ for model in EXTENSION_MODELS]
        if f"{TEXT_TO_BI_SCHEMA}.business_domains" in Model.metadata.tables:
            tables.extend((metric_domains, glossary_term_domains, expert_rule_domains))
        Model.metadata.create_all(bind=connection, tables=tables, checkfirst=True)
        if connection.dialect.name == "postgresql":
            connection.execute(text(
                f"ALTER TABLE {TEXT_TO_BI_SCHEMA}.metrics ADD COLUMN IF NOT EXISTS status "
                "VARCHAR(16) NOT NULL DEFAULT 'draft'"
            ))
