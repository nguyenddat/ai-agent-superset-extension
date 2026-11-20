import hashlib
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from text_to_bi.superset_semantic_layer.common.schemas.status_enum import ReviewStatus
from text_to_bi.superset_semantic_layer.common.utils.type_formatter import compact_json
from text_to_bi.superset_semantic_layer.core.security import can_access_dataset
from text_to_bi.superset_semantic_layer.modules.data_dictionary.dependencies import (
    column_dictionary_repository,
    dataset_dictionary_repository,
)
from text_to_bi.superset_semantic_layer.modules.glossary_management.dependencies import (
    glossary_link_repository,
    glossary_revision_repository,
    glossary_term_repository,
)
from text_to_bi.superset_semantic_layer.modules.metric_management.dependencies import metric_contract_repository
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_contract import (
    contract_is_approved_current,
    metric_contract_hash,
)
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_query_defaults import (
    query_defaults_for,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_dataset

from ..exceptions import ExpertRuleValidationError
from ..models import ExpertRuleLink


# -------------------------RESOLVE------------------------
def column_resolver(dataset_id: Any) -> Callable[[Any], Any]:
    if isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
        raise ExpertRuleValidationError("Invalid dataset_id.")
    if dataset_dictionary_repository().read(dataset_id) is None:
        return lambda _: None

    def resolve(reference: Any) -> Any:
        columns = column_dictionary_repository()
        if isinstance(reference, int) and not isinstance(reference, bool):
            return columns.read_in_dataset(dataset_id, reference)
        if isinstance(reference, str):
            # A column name is unique within a dataset, so the list holds at most one column.
            column = columns.read_by_column_name(dataset_id, reference)
            return [column] if column is not None else []
        return None

    return resolve


def glossary_links(term_id: int) -> list[Any] | None:
    revision = glossary_revision_repository().read_serving(term_id)
    if revision is None:
        return None
    # A term may describe several datasets; same-dataset enforcement is left to the caller.
    return [
        SimpleNamespace(
            status=revision.status,
            # The serving revision stays current for a rule while an edit of the term waits for review.
            is_current=True,
            dataset_id=link.dataset_id,
            content_hash=revision.content_hash,
            fingerprint=link.fingerprint,
        )
        for link in glossary_link_repository().read_by_revision(revision.id)
    ]


def approved_metric(metric_id: int) -> Any | None:
    contract = metric_contract_repository().read_by_metric(metric_id)
    dataset = get_dataset(contract.dataset_id) if contract else None
    metric = next((item for item in dataset.metrics if item.id == metric_id), None) if dataset else None
    if contract is None or dataset is None or metric is None:
        return None
    defaults = query_defaults_for(dataset.id, metric_id)
    if not contract_is_approved_current(contract, dataset, metric, defaults):
        return None
    return SimpleNamespace(
        status=contract.status,
        is_current=True,
        dataset_id=dataset.id,
        expression_hash=metric_contract_hash(dataset, metric, defaults),
    )


def glossary_term_name(term_id: int) -> str:
    term = glossary_term_repository().read(term_id)
    return term.canonical_name if term else f"#{term_id}"


def column_name(column_id: int) -> str:
    column = column_dictionary_repository().read(column_id)
    return (column.display_name or column.column_name) if column else f"#{column_id}"


def physical_column(column_id: int) -> str | None:
    column = column_dictionary_repository().read(column_id)
    return column.column_name if column else None


# -------------------------FINGERPRINT--------------------
def link_fingerprint(kind: str, target_id: int, dataset_id: int) -> str | None:
    source: Any
    if kind == "dataset":
        source = get_dataset(dataset_id)
    elif kind == "glossary":
        source = next((link for link in glossary_links(target_id) or [] if link.dataset_id == dataset_id), None)
    else:
        source = approved_metric(target_id)
    if source is None:
        return None
    identity = [kind, target_id, dataset_id, getattr(source, "status", None), getattr(source, "is_current", None)]
    if kind == "metric":
        identity.append(getattr(source, "expression_hash", None))
    if kind == "glossary":
        identity.extend([getattr(source, "content_hash", None), getattr(source, "fingerprint", None)])
    return hashlib.sha256(compact_json(identity).encode()).hexdigest()


def live_fingerprint(link: ExpertRuleLink) -> str | None:
    return link_fingerprint(link.kind, link.target_id, link.dataset_id)


def rule_links(values: dict[str, Any]) -> list[dict[str, Any]]:
    references = [
        ("dataset", values["dataset_id"]),
        *(("glossary", item) for item in values["glossary_term_ids"]),
        *(("metric", item) for item in values["metric_ids"]),
    ]
    return [
        {
            "kind": kind,
            "target_id": target_id,
            "dataset_id": values["dataset_id"],
            "fingerprint": link_fingerprint(kind, target_id, values["dataset_id"]),
        }
        for kind, target_id in references
    ]


# -------------------------CHECK--------------------------
def with_term_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    term_ids, dataset_id = payload.get("glossary_term_ids"), payload.get("dataset_id")
    if not isinstance(term_ids, list) or not isinstance(dataset_id, int):
        return payload
    metric_ids = {
        link.metric_id
        for term_id in term_ids
        if isinstance(term_id, int)
        for link in _term_links(term_id, dataset_id)
        if link.kind == "metric" and approved_metric(link.metric_id) is not None
    }
    return {**payload, "metric_ids": sorted(metric_ids)}


def validate_semantic_links(values: dict[str, Any]) -> None:
    if get_dataset(values["dataset_id"]) is None:
        raise ExpertRuleValidationError("Unknown dataset.")
    if not values["glossary_term_ids"]:
        raise ExpertRuleValidationError("An expert rule needs at least one approved glossary term.")
    for term_id in values["glossary_term_ids"]:
        matching_term = next(
            (
                term
                for term in glossary_links(term_id) or []
                if term.status == ReviewStatus.APPROVED and term.is_current and term.dataset_id == values["dataset_id"]
            ),
            None,
        )
        if matching_term is None:
            raise ExpertRuleValidationError("Invalid glossary link.")
    for metric_id in values["metric_ids"]:
        metric = approved_metric(metric_id)
        if metric is None or metric.status != ReviewStatus.APPROVED or metric.dataset_id != values["dataset_id"]:
            raise ExpertRuleValidationError("Invalid metric link.")


def rule_is_discoverable(revision: Any, links: list[ExpertRuleLink]) -> bool:
    return bool(
        revision.status == ReviewStatus.APPROVED
        and revision.is_current
        and links
        and all(live_fingerprint(link) == link.fingerprint for link in links)
    )


def linked_target_authorized(link: ExpertRuleLink) -> bool:
    dataset = get_dataset(link.dataset_id)
    if dataset is None or not can_access_dataset(dataset):
        return False
    if link.kind == "dataset":
        return True
    if link.kind == "metric":
        return approved_metric(link.target_id) is not None
    # A term may bind several datasets; only this rule's own dataset binding governs it.
    term_links = glossary_links(link.target_id) or []
    glossary_link = next((item for item in term_links if item.dataset_id == link.dataset_id), None)
    bound_dataset = get_dataset(glossary_link.dataset_id) if glossary_link is not None else None
    return bool(bound_dataset is not None and can_access_dataset(bound_dataset))


# -------------------------OPTIONS------------------------
def rule_options() -> list[dict[str, Any]]:
    terms_by_dataset: dict[int, list[dict[str, Any]]] = {}
    for revision in glossary_revision_repository().read_all_serving():
        links = glossary_link_repository().read_by_revision(revision.id)
        for dataset_id in {link.dataset_id for link in links}:
            dataset_links = [link for link in links if link.dataset_id == dataset_id]
            terms_by_dataset.setdefault(dataset_id, []).append(
                {
                    "id": revision.term_id,
                    "name": glossary_term_name(revision.term_id),
                    # The editor shows the metrics a rule inherits and lists the term's own columns first.
                    "metric_ids": sorted(
                        link.metric_id
                        for link in dataset_links
                        if link.kind == "metric" and approved_metric(link.metric_id) is not None
                    ),
                    "column_names": sorted(link.column_name for link in dataset_links if link.kind == "column"),
                }
            )
    datasets = []
    for dictionary in dataset_dictionary_repository().read_all():
        dataset = get_dataset(dictionary.id)
        if dataset is None or not can_access_dataset(dataset):
            continue
        datasets.append(
            {
                "id": dataset.id,
                "name": dataset.table_name,
                "columns": [
                    {
                        "id": column.id,
                        "column_name": column.column_name,
                        "display_name": column.display_name,
                        "data_type": column.data_type,
                    }
                    for column in column_dictionary_repository().read_by_dataset(dataset.id)
                ],
                "glossary_terms": sorted(
                    terms_by_dataset.get(dataset.id, []), key=lambda term: term["name"].casefold()
                ),
                "metrics": [
                    {"id": metric.id, "name": metric.verbose_name or metric.metric_name}
                    for metric in getattr(dataset, "metrics", [])
                    if approved_metric(metric.id) is not None
                ],
            }
        )
    datasets.sort(key=lambda item: item["name"].casefold())
    return datasets


def _term_links(term_id: int, dataset_id: int) -> list[Any]:
    revision = glossary_revision_repository().read_serving(term_id)
    if revision is None:
        return []
    return glossary_link_repository().read_by_revision_dataset(revision.id, dataset_id)
