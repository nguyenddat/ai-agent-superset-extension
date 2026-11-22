from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from superset.extensions import db

from text_to_bi.superset_text_to_bi.agent_package.get_embedding_models import OpenRouterEmbedding

from .repositories import IngestionJobRepository, QdrantRepository
from .services import ChatService, IngestionService, RetrievalService


@dataclass(frozen=True)
class IndexServices:
    index: QdrantRepository
    embedding: OpenRouterEmbedding
    session: object


def index_services() -> IndexServices:
    index = QdrantRepository()
    embedding = OpenRouterEmbedding()
    return IndexServices(index=index, embedding=embedding, session=db.session)


@contextmanager
def chat_service_factory() -> Iterator[ChatService]:
    index = QdrantRepository()
    embedding = OpenRouterEmbedding()
    service = ChatService(db.session, index, embedding)
    try:
        yield service
    finally:
        index.close()
        embedding.close()


def ingestion_job_repository() -> IngestionJobRepository:
    return IngestionJobRepository(db.session)


def ingestion_service(services: IndexServices | None = None) -> IngestionService:
    services = services or index_services()
    return IngestionService(services.session, services.index, services.embedding)


def retrieval_service(services: IndexServices | None = None) -> RetrievalService:
    services = services or index_services()
    return RetrievalService(services.session, services.index, services.embedding)
