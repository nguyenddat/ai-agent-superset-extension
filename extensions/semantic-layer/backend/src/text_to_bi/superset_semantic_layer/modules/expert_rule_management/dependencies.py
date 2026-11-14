from superset import db

from .repositories.repo_expert_rule import ExpertRuleRepository
from .repositories.repo_expert_rule_event import ExpertRuleEventRepository
from .repositories.repo_expert_rule_group import ExpertRuleGroupRepository
from .repositories.repo_expert_rule_link import ExpertRuleLinkRepository
from .repositories.repo_expert_rule_revision import ExpertRuleRevisionRepository


def expert_rule_repository() -> ExpertRuleRepository:
    return ExpertRuleRepository(db.session)


def expert_rule_revision_repository() -> ExpertRuleRevisionRepository:
    return ExpertRuleRevisionRepository(db.session)


def expert_rule_link_repository() -> ExpertRuleLinkRepository:
    return ExpertRuleLinkRepository(db.session)


def expert_rule_event_repository() -> ExpertRuleEventRepository:
    return ExpertRuleEventRepository(db.session)


def expert_rule_group_repository() -> ExpertRuleGroupRepository:
    return ExpertRuleGroupRepository(db.session)
