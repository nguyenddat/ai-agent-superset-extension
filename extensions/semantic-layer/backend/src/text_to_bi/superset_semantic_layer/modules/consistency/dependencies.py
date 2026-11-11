from superset import db

from .repositories.contradiction import ContradictionRepository
from .repositories.contradiction_judgement import ContradictionJudgementRepository


def contradiction_repository() -> ContradictionRepository:
    return ContradictionRepository(db.session)


def contradiction_judgement_repository() -> ContradictionJudgementRepository:
    return ContradictionJudgementRepository(db.session)
