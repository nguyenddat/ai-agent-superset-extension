import logging
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.agent_package.get_embedding_models import OpenRouterEmbedding
from text_to_bi.superset_text_to_bi.core.config import settings as config
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetDatabase
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import readable_datasets

from ..repositories.qdrant_repository import QdrantRepository
from ..utils.exceptions import (
    Text2SqlConnectionNotFound,
    Text2SqlInvalidRequest,
    Text2SqlRerankUnavailable,
)
from ..utils.topics import OWN_KNOWLEDGE, TOPICS
from .reranker import Reranker

logger = logging.getLogger("text2sql.topic_search")


@dataclass(frozen=True)
class TopicHit:
    entity_id: str
    table_id: int | None
    name: str
    display_name: str
    text: str
    score: float
    rerank_score: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopicSearchOutcome:
    hits: list[TopicHit]
    reranked: bool = False
    rerank_error: str | None = None


def _hit(point: dict[str, Any]) -> TopicHit:
    payload = point["payload"]
    table_id = payload.get("table_id")
    return TopicHit(
        entity_id=str(payload["entity_id"]), table_id=int(table_id) if table_id is not None else None,
        name=payload.get("name", ""), display_name=payload.get("display_name", payload.get("name", "")),
        text=payload.get("text", ""), score=round(float(point.get("score", 0.0)), 6), payload=payload,
    )


class TopicSearchService:
    def __init__(self, session: Session, index: QdrantRepository, embedding: OpenRouterEmbedding) -> None:
        self.session = session
        self.index = index
        self.embedding = embedding

    def search(
        self, database_id: int, topic: str, question: str, k: int = 5, reranker: Reranker | None = None,
        user_id: int | None = None, vector: list[float] | None = None,
    ) -> TopicSearchOutcome:
        if topic not in TOPICS:
            raise Text2SqlInvalidRequest(f"Topic không hợp lệ: {topic}.")
        dataset_ids = [
            str(dataset.id) for dataset in readable_datasets() if dataset.database_id == database_id
        ]
        if not dataset_ids:
            return TopicSearchOutcome(hits=[])
        filters: dict[str, Any] = {"dataset_id": dataset_ids}
        if topic == OWN_KNOWLEDGE:
            if user_id is None:
                raise Text2SqlInvalidRequest("Cần user_id để tìm tri thức riêng.")
            filters["user_id"] = str(user_id)
        if self.session.get(SupersetDatabase, database_id) is None:
            raise Text2SqlConnectionNotFound()
        vector = vector or self.embedding.embed([question])[0]
        pool = max(k, config.text2sql_rerank_pool) if reranker is not None else k
        points = self.index.search(question, vector, str(database_id), topic, pool, filters)
        hits = [_hit(point) for point in points]
        if reranker is None or not hits:
            return TopicSearchOutcome(hits=hits[:k])
        try:
            scores = reranker.rerank(question, [hit.text for hit in hits], topic)
        except Text2SqlRerankUnavailable as error:
            logger.warning("Rerank %s lỗi, dùng thứ tự gốc: %s", topic, error.code)
            return TopicSearchOutcome(hits=hits[:k], rerank_error=error.code)
        rescored = [replace(hit, rerank_score=round(score, 6)) for hit, score in zip(hits, scores, strict=True)]
        order = {hit.entity_id: position for position, hit in enumerate(hits)}
        rescored.sort(key=lambda hit: (-(hit.rerank_score or 0.0), order[hit.entity_id]))
        return TopicSearchOutcome(hits=rescored[:k], reranked=True)
