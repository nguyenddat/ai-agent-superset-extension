import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Select, event, func, inspect, select, update
from sqlalchemy.orm import Session
from superset.connectors.sqla.models import TableColumn

from text_to_bi.superset_text_to_bi.common.utils.request_user import request_user_id
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import (
    ColumnAggregation,
    ColumnDictionary,
    ColumnSynonym,
    IndicatorAggregation,
    SupersetDataset,
    SupersetMetric,
    TableColumnRole,
    TableDictionary,
    TableTimeGrain,
)
from text_to_bi.superset_text_to_bi.modules.expert_rule_management.models import (
    ExpertRule,
    ExpertRuleGlossaryLink,
    ExpertRuleMetricLink,
    ExpertRuleRevision,
)
from text_to_bi.superset_text_to_bi.modules.glossary_management.models import (
    GlossaryLink,
    GlossaryRevision,
    GlossaryTerm,
)
from text_to_bi.superset_text_to_bi.modules.metric_management.models import Metric
from text_to_bi.superset_text_to_bi.modules.own_knowledge.models import OwnKnowledgeEntry
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import datasets_on_database

from ..models.ingestion_job import EVENT, PENDING, IngestionJob
from ..repositories.ingestion_job_repository import enqueue_jobs
from ..utils.topics import EXPERT_RULE, GLOSSARY, METRIC, OWN_KNOWLEDGE, TOPICS

logger = logging.getLogger(__name__)

STRUCTURE_TOPICS = TOPICS
METRIC_TOPICS = (METRIC, GLOSSARY, EXPERT_RULE, OWN_KNOWLEDGE)
GLOSSARY_TOPICS = (GLOSSARY, EXPERT_RULE, OWN_KNOWLEDGE)
EXPERT_RULE_TOPICS = (EXPERT_RULE, OWN_KNOWLEDGE)
OWN_KNOWLEDGE_TOPICS = (OWN_KNOWLEDGE,)
PENDING_JOBS_KEY = "text2bi_ingestion_job_ids"

DatasetResolver = Callable[["DatasetLookup", Any], int | None]
WATCHED: dict[type, tuple[tuple[str, ...], DatasetResolver]] = {}
_registered = False


class DatasetLookup:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._cache: dict[tuple[str, UUID | int], int | None] = {}

    def _scalar(self, name: str, key: UUID | int | None, statement: Select) -> int | None:
        if key is None:
            return None
        cache_key = (name, key)
        if cache_key not in self._cache:
            self._cache[cache_key] = self.connection.execute(statement).scalar()
        return self._cache[cache_key]

    def dataset(self, dataset_id: int | None) -> int | None:
        return self._scalar(
            "dataset_database", dataset_id, select(SupersetDataset.database_id).where(SupersetDataset.id == dataset_id),
        )

    def column(self, column_id: int | None) -> int | None:
        dataset_id = self._scalar(
            "column_dataset", column_id, select(TableColumn.table_id).where(TableColumn.id == column_id),
        )
        return self.dataset(dataset_id)

    def column_dictionary(self, dictionary_id: UUID | None) -> int | None:
        dataset_id = self._scalar(
            "column_dictionary_dataset", dictionary_id,
            select(ColumnDictionary.dataset_id).where(ColumnDictionary.id == dictionary_id),
        )
        return self.dataset(dataset_id)

    def table_dictionary(self, dictionary_id: UUID | None) -> int | None:
        dataset_id = self._scalar(
            "table_dictionary_dataset", dictionary_id,
            select(TableDictionary.dataset_id).where(TableDictionary.id == dictionary_id),
        )
        return self.dataset(dataset_id)

    def glossary_term(self, term_id: UUID | None) -> int | None:
        dataset_id = self._scalar(
            "glossary_term_dataset", term_id, select(GlossaryTerm.dataset_id).where(GlossaryTerm.id == term_id),
        )
        return self.dataset(dataset_id)

    def glossary_revision(self, revision_id: UUID | None) -> int | None:
        term_id = self._scalar(
            "glossary_revision_term", revision_id,
            select(GlossaryRevision.term_id).where(GlossaryRevision.id == revision_id),
        )
        return self.glossary_term(term_id)

    def expert_rule(self, rule_id: UUID | None) -> int | None:
        dataset_id = self._scalar(
            "expert_rule_dataset", rule_id, select(ExpertRule.dataset_id).where(ExpertRule.id == rule_id),
        )
        return self.dataset(dataset_id)

    def expert_rule_revision(self, revision_id: UUID | None) -> int | None:
        rule_id = self._scalar(
            "expert_rule_revision_rule", revision_id,
            select(ExpertRuleRevision.rule_id).where(ExpertRuleRevision.id == revision_id),
        )
        return self.expert_rule(rule_id)


def _register_models() -> None:
    WATCHED.update({
        SupersetDataset: (STRUCTURE_TOPICS, lambda lookup, item: item.database_id),
        TableColumn: (STRUCTURE_TOPICS, lambda lookup, item: lookup.dataset(item.table_id)),
        TableDictionary: (STRUCTURE_TOPICS, lambda lookup, item: lookup.dataset(item.dataset_id)),
        ColumnDictionary: (STRUCTURE_TOPICS, lambda lookup, item: lookup.dataset(item.dataset_id)),
        ColumnSynonym: (STRUCTURE_TOPICS, lambda lookup, item: lookup.column_dictionary(item.column_dictionary_id)),
        ColumnAggregation: (STRUCTURE_TOPICS, lambda lookup, item: lookup.column_dictionary(item.column_dictionary_id)),
        TableTimeGrain: (STRUCTURE_TOPICS, lambda lookup, item: lookup.table_dictionary(item.table_dictionary_id)),
        TableColumnRole: (STRUCTURE_TOPICS, lambda lookup, item: lookup.table_dictionary(item.table_dictionary_id)),
        IndicatorAggregation: (
            STRUCTURE_TOPICS, lambda lookup, item: lookup.table_dictionary(item.table_dictionary_id),
        ),
        Metric: (METRIC_TOPICS, lambda lookup, item: lookup.dataset(item.dataset_id)),
        SupersetMetric: (METRIC_TOPICS, lambda lookup, item: lookup.dataset(item.table_id)),
        GlossaryTerm: (GLOSSARY_TOPICS, lambda lookup, item: lookup.dataset(item.dataset_id)),
        GlossaryRevision: (GLOSSARY_TOPICS, lambda lookup, item: lookup.glossary_term(item.term_id)),
        GlossaryLink: (GLOSSARY_TOPICS, lambda lookup, item: lookup.glossary_revision(item.revision_id)),
        ExpertRule: (EXPERT_RULE_TOPICS, lambda lookup, item: lookup.dataset(item.dataset_id)),
        ExpertRuleRevision: (EXPERT_RULE_TOPICS, lambda lookup, item: lookup.expert_rule(item.rule_id)),
        ExpertRuleGlossaryLink: (
            EXPERT_RULE_TOPICS, lambda lookup, item: lookup.expert_rule_revision(item.revision_id),
        ),
        ExpertRuleMetricLink: (EXPERT_RULE_TOPICS, lambda lookup, item: lookup.expert_rule_revision(item.revision_id)),
        OwnKnowledgeEntry: (OWN_KNOWLEDGE_TOPICS, lambda lookup, item: lookup.dataset(item.dataset_id)),
    })


def _changed_items(session: Session):
    yield from (item for item in session.new if not isinstance(item, IngestionJob))
    yield from (item for item in session.dirty if not isinstance(item, IngestionJob) and session.is_modified(item))
    yield from (item for item in session.deleted if not isinstance(item, IngestionJob))


def _has_full_dataset_access(connection: Connection, database_id: int) -> bool:
    try:
        accessible_datasets = datasets_on_database(database_id)
        total_datasets = connection.execute(
            select(func.count()).select_from(SupersetDataset).where(SupersetDataset.database_id == database_id)
        ).scalar_one()
    except Exception:
        logger.exception("Unable to verify Text2SQL ingestion access for Superset database %s", database_id)
        return False
    return len(accessible_datasets) == total_datasets


def enqueue_for_changes(session: Session, flush_context: object) -> None:
    lookup: DatasetLookup | None = None
    pending: dict[int, set[str]] = {}
    for item in _changed_items(session):
        watched = WATCHED.get(type(item))
        if watched is None:
            continue
        topics, resolve = watched
        lookup = lookup or DatasetLookup(session.connection())
        database_id = resolve(lookup, item)
        if database_id is not None:
            pending.setdefault(database_id, set()).update(topics)
    if lookup is None:
        return
    job_table = IngestionJob.__table__
    if not inspect(lookup.connection).has_table(job_table.name, schema=job_table.schema):
        return

    for database_id, affected_topics in pending.items():
        topics = [topic for topic in TOPICS if topic in affected_topics]
        user_id = request_user_id()
        can_dispatch = user_id is not None and _has_full_dataset_access(lookup.connection, database_id)
        enqueue_jobs(
            lookup.connection, [database_id], topics, EVENT,
            requested_by_user_id=user_id if can_dispatch else None,
        )
        if can_dispatch:
            assert user_id is not None
            lookup.connection.execute(
                update(IngestionJob).where(
                    IngestionJob.database_id == database_id,
                    IngestionJob.topic.in_(topics),
                    IngestionJob.status == PENDING,
                ).values(requested_by_user_id=user_id)
            )
        else:
            continue
        job_ids = lookup.connection.execute(
            select(IngestionJob.id).where(
                IngestionJob.database_id == database_id,
                IngestionJob.topic.in_(topics),
                IngestionJob.status == PENDING,
            )
        ).scalars()
        session.info.setdefault(PENDING_JOBS_KEY, set()).update(str(job_id) for job_id in job_ids)


def dispatch_after_commit(session: Session) -> None:
    job_ids = session.info.pop(PENDING_JOBS_KEY, set())
    if not job_ids:
        return
    from ..worker import process_ingestion_job

    for job_id in sorted(job_ids):
        try:
            process_ingestion_job.delay(job_id)
        except Exception:
            logger.exception("Unable to dispatch Text2SQL ingestion job %s after commit", job_id)


def discard_after_rollback(session: Session) -> None:
    session.info.pop(PENDING_JOBS_KEY, None)


def register_triggers() -> None:
    global _registered
    if _registered:
        return
    _register_models()
    event.listen(Session, "after_flush", enqueue_for_changes)
    event.listen(Session, "after_commit", dispatch_after_commit)
    event.listen(Session, "after_rollback", discard_after_rollback)
    _registered = True
