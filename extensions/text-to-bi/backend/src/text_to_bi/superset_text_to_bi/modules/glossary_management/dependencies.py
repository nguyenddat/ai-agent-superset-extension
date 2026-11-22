from superset.extensions import db

from .services import GlossaryService


def glossary_service() -> GlossaryService:
    return GlossaryService(db.session)
