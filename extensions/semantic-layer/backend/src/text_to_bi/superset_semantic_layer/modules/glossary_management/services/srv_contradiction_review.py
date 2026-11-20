import hashlib
from datetime import datetime, timezone

from text_to_bi.superset_semantic_layer.common.utils.type_formatter import compact_json
from text_to_bi.superset_semantic_layer.modules.data_dictionary.dependencies import column_dictionary_repository
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.dependencies import (
    expert_rule_link_repository,
    expert_rule_repository,
    expert_rule_revision_repository,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_dataset

from ..dependencies import (
    contradiction_judgement_repository,
    contradiction_repository,
    glossary_link_repository,
    glossary_revision_repository,
    glossary_term_repository,
)
from ..exceptions import ContradictionNotFoundError
from ..models import Contradiction, ContradictionJudgement
from .srv_contradiction_detection import (
    RULE_KINDS,
    SEMANTIC_KINDS,
    MetricItem,
    RuleItem,
    TermItem,
    detect,
    semantic_candidates,
)
from .srv_contradiction_judgement import Judge, SemanticOutcome, Verdict, judge_candidates, semantic_findings
from .srv_contradiction_lifecycle import reconcile

# Only content an administrator still stands behind is checked: a draft waiting for review, or an approved revision.
CHECKED_STATUSES = ("draft", "approved")
KIND_ORDER = {kind: index for index, kind in enumerate((*RULE_KINDS, *SEMANTIC_KINDS))}


def _governed_terms() -> tuple[list[TermItem], dict[int, int]]:
    revision_repository, link_repository = glossary_revision_repository(), glossary_link_repository()
    terms, metric_datasets = [], {}
    for term in glossary_term_repository().read_all():
        revision = revision_repository.read_current(term.id)
        if revision is None or revision.status not in CHECKED_STATUSES:
            continue
        links = link_repository.read_by_revision(revision.id)
        metric_datasets.update({link.metric_id: link.dataset_id for link in links if link.kind == "metric"})
        terms.append(
            TermItem(
                id=term.id,
                name=term.canonical_name,
                definition=revision.definition,
                content_hash=revision.content_hash,
                synonyms=tuple(revision.synonyms or ()),
                group_id=term.group_id,
                columns=frozenset((link.dataset_id, link.column_name) for link in links if link.kind == "column"),
                metric_ids=frozenset(link.metric_id for link in links if link.kind == "metric"),
            )
        )
    return terms, metric_datasets


def _linked_metrics(metric_datasets: dict[int, int]) -> list[MetricItem]:
    metrics = []
    for metric_id, dataset_id in sorted(metric_datasets.items()):
        dataset = get_dataset(dataset_id)
        metric = next((item for item in getattr(dataset, "metrics", []) if item.id == metric_id), None)
        if metric is None:
            continue
        content = compact_json([metric.metric_name, metric.verbose_name, metric.expression])
        metrics.append(
            MetricItem(
                id=metric.id,
                dataset_id=dataset_id,
                name=metric.verbose_name or metric.metric_name,
                formula=str(metric.expression),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
            )
        )
    return metrics


def _governed_rules() -> list[RuleItem]:
    rule_repository, link_repository = expert_rule_repository(), expert_rule_link_repository()
    column_repository = column_dictionary_repository()
    rules = []
    for revision in expert_rule_revision_repository().read_all_current():
        rule = rule_repository.read(revision.rule_id)
        if rule is None or revision.status not in CHECKED_STATUSES:
            continue
        columns = {
            column_id: column_repository.read(column_id)
            for column_id in {condition["field_ref"]["column_dictionary_id"] for condition in revision.conditions}
        }
        links = link_repository.read_by_revision(revision.id)
        rules.append(
            RuleItem(
                id=rule.id,
                name=revision.name,
                dataset_id=rule.dataset_id,
                content_hash=revision.content_hash,
                conditions=tuple(revision.conditions),
                exceptions=tuple(revision.exceptions or ()),
                examples=tuple(revision.examples or ()),
                term_ids=frozenset(link.target_id for link in links if link.kind == "glossary"),
                column_labels={
                    column_id: column.display_name or column.column_name
                    for column_id, column in columns.items()
                    if column
                },
                column_names={column_id: column.column_name for column_id, column in columns.items() if column},
            )
        )
    return rules


def governed_items() -> tuple[list[TermItem], list[RuleItem], list[MetricItem]]:
    terms, metric_datasets = _governed_terms()
    return terms, _governed_rules(), _linked_metrics(metric_datasets)


def refresh_contradictions(judge: Judge | None, defer_model: bool = False) -> SemanticOutcome:
    terms, rules, metrics = governed_items()
    findings = detect(terms, rules)
    candidates = semantic_candidates(terms, rules, metrics, findings)
    fingerprints = [candidate.fingerprint for candidate in candidates]
    judgement_repository = contradiction_judgement_repository()
    cached = {
        row.fingerprint: Verdict(row.contradiction, row.explanation or "")
        for row in judgement_repository.read_by_fingerprints(fingerprints)
    }
    verdicts, fresh, outcome = judge_candidates(candidates, cached, judge, defer=defer_model)
    now = datetime.now(timezone.utc)
    if outcome.status == "checked":
        judgement_repository.delete_except(fingerprints)
    for fingerprint, verdict in fresh.items():
        judgement = ContradictionJudgement(
            fingerprint=fingerprint,
            contradiction=verdict.contradiction,
            explanation=verdict.explanation or None,
            judged_at=now,
        )
        judgement_repository.add(judgement, flush=False)
    repository = contradiction_repository()
    found = [*findings, *semantic_findings(candidates, verdicts)]
    added, deleted = reconcile(repository.read_all(), found, lambda values: Contradiction(**values), now)
    for row in deleted:
        repository.delete(row)
    for row in added:
        repository.add(row, flush=False)
    repository.flush()
    return outcome


def contradictions_for_review() -> list[Contradiction]:
    rows = contradiction_repository().read_all()
    return sorted(rows, key=lambda row: (row.status != "open", KIND_ORDER.get(row.kind, len(KIND_ORDER)), row.id))


def mark_contradiction_dismissed(contradiction_id: int, reason: str, actor_id: int) -> Contradiction:
    row = contradiction_repository().read(contradiction_id)
    if row is None:
        raise ContradictionNotFoundError()
    row.status, row.dismiss_reason = "dismissed", reason
    row.dismissed_by, row.dismissed_at = actor_id, datetime.now(timezone.utc)
    return row
