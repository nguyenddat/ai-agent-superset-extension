from superset.extensions import db

from .services import ConversationService


def conversation_service() -> ConversationService:
    return ConversationService(db.session)
