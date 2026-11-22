from superset.extensions import db

from .repositories import OwnKnowledgeRepository
from .services import OwnKnowledgeService


def own_knowledge_service() -> OwnKnowledgeService:
    return OwnKnowledgeService(db.session)


def own_knowledge_repository() -> OwnKnowledgeRepository:
    return OwnKnowledgeRepository(db.session)
