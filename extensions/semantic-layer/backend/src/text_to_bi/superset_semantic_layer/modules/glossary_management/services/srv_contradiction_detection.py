import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from .srv_contradiction_conditions import (
    ColumnDomain,
    bound_differences,
    condition_phrase,
    region_contains,
    regions_overlap,
    rule_domains,
)
from .srv_contradiction_thresholds import main_clause, stated_interval
from .srv_glossary_validation import (
    normalized_name,
)

# Found by reading names, links and conditions; the same content always gives the same result.
RULE_KINDS = (
    "term_name_clash",
    "rule_conditions_empty",
    "rule_rule_same_term",
    "rule_rule_overlap",
    "rule_term_threshold",
    "rule_example_threshold",
)
# Judged by the AI model on pairs a cheap filter picked: definitions, formulas, exceptions and examples in prose.
SEMANTIC_KINDS = ("term_term_meaning", "term_metric_meaning", "rule_term_meaning", "rule_rule_meaning")


@dataclass(frozen=True)
class TermItem:
    """A glossary term's current draft or approved revision, as the checks read it."""

    id: int
    name: str
    definition: str
    content_hash: str
    synonyms: tuple[str, ...] = ()
    group_id: int | None = None
    # (dataset ID, column name) of each column link, and the IDs of the linked metrics.
    columns: frozenset = frozenset()
    metric_ids: frozenset = frozenset()


@dataclass(frozen=True)
class RuleItem:
    """An expert rule's current draft or approved revision, with the labels of the columns its conditions use."""

    id: int
    name: str
    dataset_id: int
    content_hash: str
    conditions: tuple = ()
    exceptions: tuple = ()
    examples: tuple = ()
    term_ids: frozenset = frozenset()
    column_labels: dict = field(default_factory=dict, compare=False, hash=False)
    column_names: dict = field(default_factory=dict, compare=False, hash=False)

    def label(self, column_id: int) -> str:
        return self.column_labels.get(column_id) or f"Cột #{column_id}"


@dataclass(frozen=True)
class MetricItem:
    """A metric a term links, with its formula as pseudo code."""

    id: int
    dataset_id: int
    name: str
    formula: str
    content_hash: str


@dataclass(frozen=True)
class ItemReference:
    type: str
    id: int
    name: str


@dataclass(frozen=True)
class Finding:
    """One contradiction: its kind, the one or two items involved, and what shows it."""

    kind: str
    items: tuple[ItemReference, ...]
    fingerprint: str
    evidence: tuple[str, ...]
    explanation: str

    @property
    def pair_key(self) -> str:
        return pair_key(self.kind, self.items)


@dataclass(frozen=True)
class Candidate:
    """A pair worth asking the AI model about, with each item written out for it."""

    kind: str
    items: tuple[ItemReference, ...]
    fingerprint: str
    texts: tuple[str, ...]


def pair_key(kind: str, items: Iterable[ItemReference]) -> str:
    return f"{kind}:" + "|".join(f"{item.type}:{item.id}" for item in items)


def content_fingerprint(kind: str, contents: Iterable[tuple[str, int, str]]) -> str:
    """A hash of the kind and of each involved item's type, ID and content hash.

    It changes when either item's content changes, which is what reopens a dismissed contradiction.
    """
    payload = json.dumps([kind, [list(content) for content in contents]], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _term(term: TermItem) -> ItemReference:
    return ItemReference("term", term.id, term.name)


def _rule(rule: RuleItem) -> ItemReference:
    return ItemReference("rule", rule.id, rule.name)


def _metric(metric: MetricItem) -> ItemReference:
    return ItemReference("metric", metric.id, metric.name)


def _content(item: Any) -> tuple[str, int, str]:
    kind = "term" if isinstance(item, TermItem) else "rule" if isinstance(item, RuleItem) else "metric"
    return kind, item.id, item.content_hash


def _finding(kind: str, involved: tuple, evidence: list[str], explanation: str) -> Finding:
    references = tuple(_term(item) if isinstance(item, TermItem) else _rule(item) for item in involved)
    fingerprint = content_fingerprint(kind, [_content(item) for item in involved])
    return Finding(kind, references, fingerprint, tuple(evidence), explanation)


def _quoted_names(names: Iterable[str]) -> str:
    return ", ".join(f"“{name}”" for name in names)


def _term_names(term_ids: Iterable[int], terms: dict[int, TermItem]) -> str:
    names = [terms[term_id].name if term_id in terms else f"#{term_id}" for term_id in sorted(term_ids)]
    return _quoted_names(names) or "không gắn thuật ngữ"


def name_clashes(terms: list[TermItem]) -> list[Finding]:
    """Two terms claim the same word as their name or a synonym, so a question using it could mean either.

    Terms an administrator put in one group mean the same thing, so a shared word between them is expected.
    """
    claims: dict[str, list[tuple[TermItem, str, str]]] = {}
    for term in terms:
        words = [(term.name, "tên"), *((synonym, "từ đồng nghĩa") for synonym in term.synonyms)]
        for word, role in words:
            claims.setdefault(normalized_name(word), []).append((term, word, role))
    clashes: dict[tuple[TermItem, TermItem], list[str]] = {}
    for claimants in claims.values():
        for (first, word, first_role), (second, _, second_role) in combinations(claimants, 2):
            if first.id == second.id or (first.group_id is not None and first.group_id == second.group_id):
                continue
            if first.id > second.id:
                first, second, first_role, second_role = second, first, second_role, first_role
            line = f"“{word}” là {first_role} của “{first.name}” và là {second_role} của “{second.name}”."
            clashes.setdefault((first, second), []).append(line)
    return [
        _finding(
            "term_name_clash",
            pair,
            lines,
            "Người dùng hỏi bằng từ này, AI Agent không biết đó là thuật ngữ nào. Đổi từ đồng nghĩa, hoặc gom hai "
            "thuật ngữ vào một nhóm nếu chúng cùng nghĩa.",
        )
        for pair, lines in sorted(clashes.items(), key=lambda item: (item[0][0].id, item[0][1].id))
    ]


def empty_rules(rules: list[RuleItem]) -> list[Finding]:
    """A rule whose own conditions on one column can never hold together, so it never applies."""
    findings = []
    for rule in rules:
        domains = rule_domains(rule.conditions)
        empty = [column_id for column_id, domain in domains.items() if domain.is_empty()]
        if not empty:
            continue
        lines = [
            " VÀ ".join(
                condition_phrase(condition, rule.label(column_id))
                for condition in rule.conditions
                if condition["field_ref"]["column_dictionary_id"] == column_id
            )
            for column_id in empty
        ]
        findings.append(
            _finding(
                "rule_conditions_empty",
                (rule,),
                lines,
                "Không giá trị nào thỏa cùng lúc các điều kiện này, nên rule không bao giờ áp dụng.",
            )
        )
    return findings


def _threshold_columns(domains: dict[int, ColumnDomain]) -> list[int]:
    return sorted(column_id for column_id, domain in domains.items() if domain.is_threshold())


def _differing_lines(first: RuleItem, second: RuleItem, first_domains: dict, second_domains: dict) -> list[str]:
    lines = []
    for column_id in sorted(first_domains.keys() | second_domains.keys()):
        first_domain, second_domain = first_domains.get(column_id), second_domains.get(column_id)
        if first_domain == second_domain:
            continue
        label = first.label(column_id) if column_id in first.column_labels else second.label(column_id)
        for rule, domain in ((first, first_domain), (second, second_domain)):
            described = domain.describe(label) if domain else f"{label}: không ràng buộc"
            lines.append(f"Rule “{rule.name}”: {described}")
    return lines


def rule_pairs(rules: list[RuleItem], terms: dict[int, TermItem]) -> list[Finding]:
    """Two rules on one dataset that disagree about which rows a concept covers.

    - `rule_rule_same_term`: both define the same glossary term, with different conditions.
    - `rule_rule_overlap`: they define different terms on the same columns, and some rows satisfy both, with neither
      rule's rows simply inside the other's (a stricter grade nested in a looser one is how levels are written).
    """
    findings = []
    ordered = sorted(rules, key=lambda rule: rule.id)
    for first, second in combinations(ordered, 2):
        if first.dataset_id != second.dataset_id:
            continue
        first_domains, second_domains = rule_domains(first.conditions), rule_domains(second.conditions)
        if not first_domains or not second_domains:
            continue
        if any(domain.is_empty() for domain in [*first_domains.values(), *second_domains.values()]):
            continue
        overlap = regions_overlap(first_domains, second_domains)
        first_inside = region_contains(second_domains, first_domains)
        second_inside = region_contains(first_domains, second_domains)
        shared_terms = sorted(first.term_ids & second.term_ids)
        lines = _differing_lines(first, second, first_domains, second_domains)
        if shared_terms:
            if first_domains == second_domains:
                continue
            names = _term_names(shared_terms, terms)
            relation = (
                "không có dòng nào thỏa cả hai" if not overlap
                else "một rule nằm trọn trong rule kia" if first_inside or second_inside
                else "chỉ giao nhau một phần"
            )
            explanation = (
                f"Hai rule cùng định nghĩa {names} nhưng điều kiện khác nhau ({relation}); AI Agent có thể áp điều "
                "kiện của rule này hoặc rule kia cho cùng một câu hỏi."
            )
            findings.append(_finding("rule_rule_same_term", (first, second), lines, explanation))
            continue
        if first_domains.keys() != second_domains.keys() or not overlap:
            continue
        if first_inside != second_inside:
            continue
        if first_domains == second_domains:
            lines = [f"Cả hai: {domain.describe(first.label(column))}" for column, domain in first_domains.items()]
            explanation = "Hai rule có điều kiện giống hệt nhau nhưng định nghĩa hai khái niệm khác nhau"
        else:
            explanation = "Có dòng dữ liệu thỏa cả hai rule nhưng hai rule định nghĩa hai khái niệm khác nhau"
        explanation += f" ({_term_names(first.term_ids, terms)} và {_term_names(second.term_ids, terms)}), "
        explanation += "nên cùng một dòng bị xếp vào cả hai."
        findings.append(_finding("rule_rule_overlap", (first, second), lines, explanation))
    return findings


def _rule_threshold_column(rule: RuleItem, domains: dict[int, ColumnDomain], term: TermItem) -> int | None:
    """The column a term's stated threshold is about: the rule's only threshold column, or else the only one of its
    threshold columns that the term links."""
    columns = _threshold_columns(domains)
    if len(columns) == 1:
        return columns[0]
    linked = [column_id for column_id in columns if (rule.dataset_id, rule.column_names.get(column_id)) in term.columns]
    return linked[0] if len(linked) == 1 else None


def rule_term_thresholds(rules: list[RuleItem], terms: dict[int, TermItem]) -> list[Finding]:
    """A rule's threshold differs from the one stated by the definition of a term it links."""
    findings = []
    for rule in sorted(rules, key=lambda item: item.id):
        domains = rule_domains(rule.conditions)
        if any(domain.is_empty() for domain in domains.values()):
            continue
        for term_id in sorted(rule.term_ids):
            term = terms.get(term_id)
            stated = stated_interval(term.definition) if term else None
            column_id = _rule_threshold_column(rule, domains, term) if stated else None
            if column_id is None:
                continue
            differences = bound_differences(stated, domains[column_id].interval)
            if not differences:
                continue
            label = rule.label(column_id)
            lines = [
                f"Thuật ngữ “{term.name}”: “{main_clause(term.definition)}” → {ColumnDomain(stated).describe(label)}",
                f"Rule “{rule.name}”: {domains[column_id].describe(label)}",
            ]
            explanation = (
                f"Điều kiện của rule khác định nghĩa của thuật ngữ nó gắn ({'; '.join(differences)}), nên câu trả lời "
                "phụ thuộc vào việc AI Agent đọc thuật ngữ hay rule."
            )
            findings.append(_finding("rule_term_threshold", (rule, term), lines, explanation))
    return findings


def example_thresholds(rules: list[RuleItem]) -> list[Finding]:
    """An example question or its intent states a threshold other than the rule's own condition."""
    findings = []
    for rule in sorted(rules, key=lambda item: item.id):
        domains = rule_domains(rule.conditions)
        columns = _threshold_columns(domains)
        if len(columns) != 1 or domains[columns[0]].is_empty():
            continue
        domain = domains[columns[0]]
        label = rule.label(columns[0])
        lines, differences = [], []
        for example in rule.examples:
            for text in (example.get("question"), example.get("intent")):
                stated = stated_interval(text)
                found = bound_differences(stated, domain.interval) if stated else []
                if found:
                    lines.append(f"Câu hỏi mẫu: “{main_clause(text)}” → {ColumnDomain(stated).describe(label)}")
                    differences.extend(found)
        if not lines:
            continue
        lines.append(f"Điều kiện của rule: {domain.describe(label)}")
        explanation = (
            f"Câu hỏi mẫu nêu ngưỡng khác điều kiện của chính rule ({'; '.join(dict.fromkeys(differences))}); AI Agent "
            "học theo câu hỏi mẫu sẽ dùng sai ngưỡng."
        )
        findings.append(_finding("rule_example_threshold", (rule,), lines, explanation))
    return findings


def detect(terms: list[TermItem], rules: list[RuleItem]) -> list[Finding]:
    """Every contradiction found by reading names, links and conditions, at most one per kind and items."""
    terms_by_id = {term.id: term for term in terms}
    findings = [
        *name_clashes(terms),
        *empty_rules(rules),
        *rule_pairs(rules, terms_by_id),
        *rule_term_thresholds(rules, terms_by_id),
        *example_thresholds(rules),
    ]
    return list({finding.pair_key: finding for finding in findings}.values())


def term_text(term: TermItem) -> str:
    text = f"Thuật ngữ “{term.name}”. Định nghĩa: {term.definition}"
    return text + (f" Từ đồng nghĩa: {', '.join(term.synonyms)}." if term.synonyms else "")


def metric_text(metric: MetricItem) -> str:
    return f"Metric “{metric.name}”. Công thức: {metric.formula}"


def rule_text(rule: RuleItem, terms: dict[int, TermItem]) -> str:
    conditions = " VÀ ".join(
        condition_phrase(condition, rule.label(condition["field_ref"]["column_dictionary_id"]))
        for condition in rule.conditions
    )
    parts = [f"Rule “{rule.name}”. Điều kiện: {conditions}."]
    names = [terms[term_id].name for term_id in sorted(rule.term_ids) if term_id in terms]
    if names:
        parts.append(f"Gắn thuật ngữ: {', '.join(names)}.")
    parts.extend(f"Ngoại lệ: khi {item.get('when')} thì {item.get('outcome')}." for item in rule.exceptions)
    parts.extend(f"Câu hỏi mẫu: “{item.get('question')}” → {item.get('intent')}." for item in rule.examples)
    return " ".join(parts)


def _mentions(term: TermItem, other: TermItem) -> bool:
    """`other`'s name or a synonym appears in `term`'s definition, so one term is described through the other."""
    definition = f" {normalized_name(term.definition)} "
    return any(f" {normalized_name(word)} " in definition for word in (other.name, *other.synonyms))


def _related_terms(first: TermItem, second: TermItem) -> bool:
    return bool(
        first.columns & second.columns
        or first.metric_ids & second.metric_ids
        or (first.group_id is not None and first.group_id == second.group_id)
        or _mentions(first, second)
        or _mentions(second, first)
    )


def _candidate(kind: str, involved: tuple, texts: tuple[str, ...]) -> Candidate:
    references = tuple(
        _term(item) if isinstance(item, TermItem) else _rule(item) if isinstance(item, RuleItem) else _metric(item)
        for item in involved
    )
    return Candidate(kind, references, content_fingerprint(kind, [_content(item) for item in involved]), texts)


def semantic_candidates(
    terms: list[TermItem], rules: list[RuleItem], metrics: list[MetricItem], findings: list[Finding]
) -> list[Candidate]:
    """The pairs whose prose the AI model judges, chosen cheaply so only related content is sent.

    Terms sharing a column or metric link, a group, or naming each other in a definition; each term with each metric
    it links; each rule with each term it links; and rules on one dataset sharing a term or a condition column. A pair
    already shown contradictory by a rule-based check is not sent again.
    """
    flagged = {frozenset((item.type, item.id) for item in finding.items) for finding in findings}

    def already_flagged(*items: ItemReference) -> bool:
        return frozenset((item.type, item.id) for item in items) in flagged

    terms = sorted(terms, key=lambda term: term.id)
    terms_by_id = {term.id: term for term in terms}
    metrics_by_id = {metric.id: metric for metric in metrics}
    candidates = []
    for first, second in combinations(terms, 2):
        if _related_terms(first, second) and not already_flagged(_term(first), _term(second)):
            candidates.append(_candidate("term_term_meaning", (first, second), (term_text(first), term_text(second))))
    for term in terms:
        for metric_id in sorted(term.metric_ids):
            metric = metrics_by_id.get(metric_id)
            if metric is not None:
                texts = (term_text(term), metric_text(metric))
                candidates.append(_candidate("term_metric_meaning", (term, metric), texts))
    rules = sorted(rules, key=lambda rule: rule.id)
    for rule in rules:
        for term_id in sorted(rule.term_ids):
            term = terms_by_id.get(term_id)
            if term is not None and not already_flagged(_rule(rule), _term(term)):
                texts = (rule_text(rule, terms_by_id), term_text(term))
                candidates.append(_candidate("rule_term_meaning", (rule, term), texts))
    for first, second in combinations(rules, 2):
        if first.dataset_id != second.dataset_id or already_flagged(_rule(first), _rule(second)):
            continue
        shared_columns = rule_domains(first.conditions).keys() & rule_domains(second.conditions).keys()
        if first.term_ids & second.term_ids or shared_columns:
            texts = (rule_text(first, terms_by_id), rule_text(second, terms_by_id))
            candidates.append(_candidate("rule_rule_meaning", (first, second), texts))
    return candidates
