from superset.extensions import db

from .services import ExpertRuleService


def expert_rule_service() -> ExpertRuleService:
    return ExpertRuleService(db.session)
