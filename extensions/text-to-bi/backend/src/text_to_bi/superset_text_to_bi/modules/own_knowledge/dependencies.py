from superset.extensions import db

from .repositories import UserDefinitionRepository
from .services import OwnKnowledgeService


def own_knowledge_service() -> OwnKnowledgeService:
    return OwnKnowledgeService(db.session)


def user_definition_repository() -> UserDefinitionRepository:
    return UserDefinitionRepository(db.session)
