from superset import db

from .repositories.glossary_term import GlossaryTermRepository
from .repositories.glossary_term_audit_event import GlossaryTermAuditEventRepository
from .repositories.glossary_term_group import GlossaryTermGroupRepository
from .repositories.glossary_term_link import GlossaryTermLinkRepository
from .repositories.glossary_term_revision import GlossaryTermRevisionRepository
from .repositories.group_suggestion_dismissal import GroupSuggestionDismissalRepository
from .repositories.text_embedding import TextEmbeddingRepository


def glossary_term_repository() -> GlossaryTermRepository:
    return GlossaryTermRepository(db.session)


def glossary_term_revision_repository() -> GlossaryTermRevisionRepository:
    return GlossaryTermRevisionRepository(db.session)


def glossary_term_link_repository() -> GlossaryTermLinkRepository:
    return GlossaryTermLinkRepository(db.session)


def glossary_term_audit_event_repository() -> GlossaryTermAuditEventRepository:
    return GlossaryTermAuditEventRepository(db.session)


def glossary_term_group_repository() -> GlossaryTermGroupRepository:
    return GlossaryTermGroupRepository(db.session)


def text_embedding_repository() -> TextEmbeddingRepository:
    return TextEmbeddingRepository(db.session)


def group_suggestion_dismissal_repository() -> GroupSuggestionDismissalRepository:
    return GroupSuggestionDismissalRepository(db.session)
