from datetime import datetime, timezone
from typing import Any

from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.core.security import can_access_dataset
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_dataset, get_datasets

from ..dependencies import expert_rule_link_repository, expert_rule_repository, expert_rule_revision_repository
from ..exceptions import (
    ExpertRuleConflictError,
    ExpertRuleNotFoundError,
    ExpertRuleSelfApprovalError,
    ExpertRuleValidationError,
)
from ..models import ExpertRule, ExpertRuleLink, ExpertRuleRevision
from .srv_expert_rule_event import ExpertRuleEventService
from .srv_expert_rule_group import ExpertRuleGroupService
from .srv_expert_rule_link import (
    column_resolver,
    linked_target_authorized,
    live_fingerprint,
    rule_is_discoverable,
    rule_links,
    validate_semantic_links,
    with_term_metrics,
)
from .srv_expert_rule_validation import (
    content_hash,
    group_id_of,
    normalize_rule_payload,
    review_reason,
    without_group,
)

RULE_CHANGED = "The expert rule changed; refresh and retry."
NAME_TAKEN = "An expert rule with this name already exists."
OUTDATED = "outdated"


class ExpertRuleService:
    def __init__(self) -> None:
        self.rules = expert_rule_repository()
        self.revisions = expert_rule_revision_repository()
        self.links = expert_rule_link_repository()
        self.groups = ExpertRuleGroupService()
        self.events = ExpertRuleEventService()

    # -------------------------CREATE-------------------------
    def create(self, payload: Any, actor_id: int) -> ExpertRuleRevision:
        payload = with_term_metrics(payload)
        group_id = group_id_of(payload)
        values = normalize_rule_payload(without_group(payload), column_resolver(payload.get("dataset_id")))
        validate_semantic_links(values)
        if self.rules.read_by_normalized_name(values["normalized_name"]) is not None:
            raise ExpertRuleValidationError(NAME_TAKEN)
        rule = ExpertRule(normalized_name=values["normalized_name"], dataset_id=values["dataset_id"])
        if group_id is not None:
            rule.group = self.groups.require(group_id)
        self.rules.add(rule)
        revision = self._create_revision(rule.id, 1, 1, values)
        self.events.create(revision, "created", actor_id)
        return revision

    # -------------------------READ---------------------------
    def read(self, rule_id: int) -> ExpertRule | None:
        return self.rules.read(rule_id)

    def require_current(self, rule_id: int) -> ExpertRuleRevision:
        revision = self.revisions.read_current(rule_id)
        if revision is None:
            raise ExpertRuleNotFoundError()
        return revision

    def read_links(self, revision: ExpertRuleRevision) -> list[ExpertRuleLink]:
        return self.links.read_by_revision(revision.id)

    def read_for_review(self) -> list[tuple[ExpertRule, ExpertRuleRevision]]:
        latest: dict[int, ExpertRuleRevision] = {}
        for revision in self.revisions.read_all():
            kept = latest.get(revision.rule_id)
            if kept is None or revision.is_current or not kept.is_current:
                latest[revision.rule_id] = revision
        rules = {rule.id: rule for rule in self.rules.read_all()}
        datasets = {dataset.id: dataset for dataset in get_datasets({rule.dataset_id for rule in rules.values()})}
        result = []
        for revision in latest.values():
            rule = rules.get(revision.rule_id)
            dataset = datasets.get(rule.dataset_id) if rule else None
            if rule is not None and (dataset is None or can_access_dataset(dataset)):
                result.append((rule, revision))
        return result

    def read_discoverable(self) -> list[tuple[ExpertRule, ExpertRuleRevision, list[ExpertRuleLink]]]:
        result = []
        for revision in self.revisions.read_all_approved_current():
            rule = self.rules.read(revision.rule_id)
            dataset = get_dataset(rule.dataset_id) if rule else None
            if dataset is None or not can_access_dataset(dataset):
                continue
            links = self.links.read_by_revision(revision.id)
            if all(linked_target_authorized(link) for link in links) and rule_is_discoverable(revision, links):
                result.append((rule, revision, links))
        return result

    @staticmethod
    def review_state(revision: ExpertRuleRevision, links: list[ExpertRuleLink]) -> str:
        if revision.status != ReviewStatus.APPROVED:
            return revision.status
        return ReviewStatus.APPROVED.value if rule_is_discoverable(revision, links) else OUTDATED

    def read_rule_readable(self, rule_id: int) -> bool:
        rule = self.rules.read(rule_id)
        if rule is None:
            raise ExpertRuleNotFoundError()
        dataset = get_dataset(rule.dataset_id)
        return dataset is None or can_access_dataset(dataset)

    # -------------------------UPDATE-------------------------
    def update(self, rule_id: int, payload: Any, expected_revision: int, actor_id: int) -> ExpertRuleRevision:
        revision = self._locked_current(rule_id, expected_revision)
        content = with_term_metrics({key: value for key, value in payload.items() if key != "expected_revision"})
        group_given = "group_id" in content
        group_id = group_id_of(content)
        group = None if group_id is None else self.groups.require(group_id)
        values = normalize_rule_payload(without_group(content), column_resolver(content.get("dataset_id")))
        validate_semantic_links(values)
        rule = self.rules.read_fresh(revision.rule_id)
        if rule is None or values["dataset_id"] != rule.dataset_id:
            raise ExpertRuleValidationError("An expert rule cannot move datasets.")
        # A rename moves the rule's unique name key with it, so the old name is free and a file import finds the rule.
        if values["normalized_name"] != rule.normalized_name:
            if self.rules.read_by_normalized_name(values["normalized_name"]) is not None:
                raise ExpertRuleValidationError(NAME_TAKEN)
            rule.normalized_name = values["normalized_name"]
        revision.is_current = False
        next_revision = self._create_revision(
            revision.rule_id, revision.revision_number + 1, revision.lifecycle_version + 1, values
        )
        self.events.create(next_revision, "updated", actor_id)
        if group_given:
            self.groups.place_rule(rule, group, actor_id)
        return next_revision

    def approve(
        self, rule_id: int, expected_revision: int, actor_id: int, reason: Any, require_second_reviewer: bool
    ) -> ExpertRuleRevision:
        revision = self._locked_current(rule_id, expected_revision)
        clean_reason = review_reason(reason)
        if revision.status != ReviewStatus.DRAFT:
            raise ExpertRuleValidationError("Cannot approve this expert rule.")
        if require_second_reviewer and self.events.read_author_id(revision) == actor_id:
            raise ExpertRuleSelfApprovalError()
        links = self.read_links(revision)
        if not links or any(not link.fingerprint or live_fingerprint(link) != link.fingerprint for link in links):
            raise ExpertRuleValidationError("Liên kết của rule đã thay đổi; lưu lại bản nháp trước khi duyệt.")
        revision.status = ReviewStatus.APPROVED.value
        revision.approver_id, revision.approved_at = actor_id, datetime.now(timezone.utc)
        revision.lifecycle_version += 1
        self.events.create(revision, "approved", actor_id, clean_reason)
        return revision

    def revoke(self, rule_id: int, expected_revision: int, actor_id: int, reason: Any) -> ExpertRuleRevision:
        revision = self._locked_current(rule_id, expected_revision)
        clean_reason = review_reason(reason)
        if revision.status != ReviewStatus.APPROVED or not clean_reason:
            raise ExpertRuleValidationError("Cannot revoke this expert rule.")
        revision.status = ReviewStatus.REVOKED.value
        revision.revoker_id, revision.revoked_at = actor_id, datetime.now(timezone.utc)
        revision.lifecycle_version += 1
        self.events.create(revision, "revoked", actor_id, clean_reason)
        return revision

    # -------------------------HELPERS------------------------
    def _create_revision(
        self, rule_id: int, revision_number: int, lifecycle_version: int, values: dict[str, Any]
    ) -> ExpertRuleRevision:
        revision = self.revisions.create(
            {
                "rule_id": rule_id,
                "revision_number": revision_number,
                "lifecycle_version": lifecycle_version,
                "name": values["name"],
                "conditions": values["conditions"],
                "exceptions": values["exceptions"],
                "examples": values["examples"],
                "content_hash": content_hash(values),
                "status": ReviewStatus.DRAFT.value,
                "is_current": True,
            }
        )
        for link in rule_links(values):
            self.links.create({"revision_id": revision.id, **link}, flush=False)
        return revision

    def _locked_current(self, rule_id: int, expected_revision: int) -> ExpertRuleRevision:
        if self.revisions.read_current(rule_id) is None:
            raise ExpertRuleNotFoundError()
        rule = self.rules.read_for_update(rule_id)
        current = self.revisions.read_current_for_update(rule_id)
        if rule is None or current is None or current.lifecycle_version != expected_revision:
            raise ExpertRuleConflictError(RULE_CHANGED)
        return current
