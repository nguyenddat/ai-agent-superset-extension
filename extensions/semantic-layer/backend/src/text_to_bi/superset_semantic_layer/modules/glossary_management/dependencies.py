from superset import db

from .repositories.repo_contradiction import ContradictionRepository
from .repositories.repo_contradiction_judgement import ContradictionJudgementRepository
from .repositories.repo_glossary_event import GlossaryEventRepository
from .repositories.repo_glossary_group import GlossaryGroupRepository
from .repositories.repo_glossary_link import GlossaryLinkRepository
from .repositories.repo_glossary_revision import GlossaryRevisionRepository
from .repositories.repo_glossary_term import GlossaryTermRepository
from .repositories.repo_group_suggestion_dismissal import GroupSuggestionDismissalRepository
from .repositories.repo_text_embedding import TextEmbeddingRepository


def glossary_term_repository() -> GlossaryTermRepository:
    return GlossaryTermRepository(db.session)


def glossary_revision_repository() -> GlossaryRevisionRepository:
    return GlossaryRevisionRepository(db.session)


def glossary_link_repository() -> GlossaryLinkRepository:
    return GlossaryLinkRepository(db.session)


def glossary_event_repository() -> GlossaryEventRepository:
    return GlossaryEventRepository(db.session)


def glossary_group_repository() -> GlossaryGroupRepository:
    return GlossaryGroupRepository(db.session)


def text_embedding_repository() -> TextEmbeddingRepository:
    return TextEmbeddingRepository(db.session)


def group_suggestion_dismissal_repository() -> GroupSuggestionDismissalRepository:
    return GroupSuggestionDismissalRepository(db.session)


def contradiction_repository() -> ContradictionRepository:
    return ContradictionRepository(db.session)


def contradiction_judgement_repository() -> ContradictionJudgementRepository:
    return ContradictionJudgementRepository(db.session)
