import logging
import unicodedata
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.agent_package.get_embedding_models import OpenRouterEmbedding
from text_to_bi.superset_text_to_bi.core.config import settings as config
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import (
    SupersetDatabase,
    SupersetDataset,
    SupersetDatasetColumn,
)
from text_to_bi.superset_text_to_bi.modules.metric_management.models import Metric
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import readable_datasets

from ..repositories.qdrant_repository import QdrantRepository
from ..utils.exceptions import Text2SqlConnectionNotFound, Text2SqlRerankUnavailable
from .catalog_context import load_context
from .index_documents import build_metric_documents, referenced_columns
from .reranker import Reranker

logger = logging.getLogger("text2sql.retrieve")


@dataclass(frozen=True)
class MetricCandidate:
    metric_id: str
    table_id: int
    name: str
    label: str | None
    description: str | None
    score: float
    matched_topics: list[str]
    rerank_score: float | None = None


@dataclass(frozen=True)
class RetrievalOutcome:
    candidates: list[MetricCandidate]
    reranked: bool = False
    rerank_error: str | None = None


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return " ".join("".join(character for character in normalized if unicodedata.category(character) != "Mn").split())


class RetrievalService:
    def __init__(self, session: Session, index: QdrantRepository, embedding: OpenRouterEmbedding) -> None:
        self.session = session
        self.index = index
        self.embedding = embedding

    def top_metrics(
        self, database_id: int, question: str, k: int = 5, reranker: Reranker | None = None
    ) -> list[MetricCandidate]:
        return self.search(database_id, question, k, reranker).candidates

    def search(
        self, database_id: int, question: str, k: int = 5, reranker: Reranker | None = None,
        vector: list[float] | None = None,
    ) -> RetrievalOutcome:
        ranked = self._ranked_candidates(database_id, question, k, vector)
        pool = ranked[:max(k, config.text2sql_rerank_pool)]
        if reranker is None or not pool:
            return RetrievalOutcome(candidates=ranked[:k])
        try:
            passages = self._passages(database_id, pool)
            scores = reranker.rerank(question, passages, "metric")
        except Text2SqlRerankUnavailable as error:
            logger.warning("Rerank lỗi, dùng thứ tự gốc: %s", error.code)
            return RetrievalOutcome(candidates=ranked[:k], rerank_error=error.code)
        rescored = [
            replace(candidate, rerank_score=round(score, 6)) for candidate, score in zip(pool, scores, strict=True)
        ]
        rescored.sort(key=lambda candidate: (
            -(candidate.rerank_score or 0.0), -candidate.score, candidate.name, str(candidate.metric_id)
        ))
        return RetrievalOutcome(candidates=rescored[:k], reranked=True)

    def _passages(self, database_id: int, candidates: list[MetricCandidate]) -> list[str]:
        documents = {
            document.entity_id: document.text
            for document in build_metric_documents(self.session, load_context(self.session, database_id))
        }
        return [
            documents.get(str(candidate.metric_id), f"Metric: {candidate.label or candidate.name}")
            for candidate in candidates
        ]

    def _ranked_candidates(
        self, database_id: int, question: str, k: int, vector: list[float] | None = None
    ) -> list[MetricCandidate]:
        if self.session.get(SupersetDatabase, database_id) is None:
            raise Text2SqlConnectionNotFound()
        vector = vector or self.embedding.embed([question])[0]
        hits = {
            topic: self.index.search(question, vector, str(database_id), topic, limit)
            for topic, limit in (("metric", max(30, k * 6)), ("table", 15), ("column", 30))
        }
        metric_ranks = {point["payload"]["entity_id"]: rank for rank, point in enumerate(hits["metric"])}
        table_ranks = {point["payload"]["table_id"]: rank for rank, point in enumerate(hits["table"])}
        column_ranks = {point["payload"]["entity_id"]: rank for rank, point in enumerate(hits["column"])}
        accessible_dataset_ids = [
            dataset.id for dataset in readable_datasets() if dataset.database_id == database_id
        ]
        if not accessible_dataset_ids:
            return []
        metrics = self.session.scalars(
            select(Metric)
            .join(SupersetDataset, Metric.dataset_id == SupersetDataset.id)
            .where(
                SupersetDataset.database_id == database_id,
                Metric.dataset_id.in_(accessible_dataset_ids),
                Metric.is_active.is_(True),
                Metric.status == "approved",
            )
        ).all()
        table_ids = {metric.dataset_id for metric in metrics}
        columns_by_table: dict[int, dict[str, int]] = {}
        if table_ids and column_ranks:
            for column in self.session.scalars(
                select(SupersetDatasetColumn).where(SupersetDatasetColumn.table_id.in_(table_ids))
            ):
                columns_by_table.setdefault(column.table_id, {})[column.column_name.lower()] = column.id
        candidates: list[MetricCandidate] = []
        for metric in metrics:
            metric_id = str(metric.id)
            table_id = str(metric.dataset_id)
            direct_rank = metric_ranks.get(metric_id)
            table_rank = table_ranks.get(table_id)
            metric_column_ids = (
                referenced_columns(metric.expression, columns_by_table.get(metric.dataset_id, {}))
                if column_ranks else []
            )
            matching_columns = [
                column_ranks[column_id] for column_id in metric_column_ids
                if column_id in column_ranks
            ]
            if direct_rank is None and table_rank is None and not matching_columns:
                continue
            score = 1 / (direct_rank + 1) if direct_rank is not None else 0.0
            if table_rank is not None:
                score += 0.12 / (table_rank + 1)
            if matching_columns:
                score += 0.18 / (min(matching_columns) + 1)
            query = _normalized(question)
            if any(_normalized(name) in query for name in (metric.name, metric.label) if name):
                score += 0.2
            topics = [topic for topic, matched in (
                ("metric", direct_rank is not None), ("table", table_rank is not None),
                ("column", bool(matching_columns)),
            ) if matched]
            candidates.append(MetricCandidate(
                metric_id=metric_id, table_id=metric.dataset_id, name=metric.name,
                label=metric.label, description=metric.description, score=round(score, 6), matched_topics=topics,
            ))
        return sorted(candidates, key=lambda candidate: (-candidate.score, candidate.name, str(candidate.metric_id)))
