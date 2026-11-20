import hashlib
import json
from collections.abc import Callable
from typing import Any

from superset.connectors.sqla.models import SqlaTable

from text_to_bi.superset_semantic_layer.core.security import can_access_dataset
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_contract import (
    MetricContractService,
    contract_is_approved_current,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import (
    connection_identity,
    datasets_by_name,
    get_dataset,
    is_internal_dataset,
)

from ..dependencies import glossary_link_repository, glossary_revision_repository
from ..exceptions import GlossaryValidationError
from ..models import GlossaryTermLink
from .srv_glossary_validation import LINK_KINDS


# -------------------------READ---------------------------
def read_links(revision_id: int) -> list[GlossaryTermLink]:
    return glossary_link_repository().read_by_revision(revision_id)


def link_target(link: GlossaryTermLink, dataset: SqlaTable) -> Any | None:
    if link.kind == "dataset":
        return None
    if link.kind == "column":
        return next((column for column in dataset.columns if column.column_name == link.column_name), None)
    return next((metric for metric in dataset.metrics if metric.id == link.metric_id), None)


def metric_approved(dataset: SqlaTable, metric: Any) -> bool:
    contracts = MetricContractService()
    contract = contracts.read(dataset, metric)
    return contract is not None and contract_is_approved_current(
        contract, dataset, metric, contracts.query_defaults(dataset, metric)
    )


def link_options() -> list[dict[str, Any]]:
    datasets = []
    for dataset in datasets_by_name():
        if is_internal_dataset(dataset) or not can_access_dataset(dataset):
            continue
        datasets.append(
            {
                "id": dataset.id,
                "name": dataset.table_name,
                "columns": [
                    {"column_name": column.column_name, "name": column.verbose_name or column.column_name}
                    for column in dataset.columns
                    if column.is_active is True and not column.expression
                ],
                # A term builds on approved metrics only, so a metric must pass review before a term can name it.
                "metrics": [
                    {"id": metric.id, "name": metric.verbose_name or metric.metric_name}
                    for metric in dataset.metrics
                    if metric_approved(dataset, metric)
                ],
            }
        )
    datasets.sort(key=lambda item: item["name"].casefold())
    return datasets


# -------------------------CHECK--------------------------
def link_fingerprint(dataset: Any, kind: str, target: Any | None = None) -> str:
    if kind not in LINK_KINDS:
        raise GlossaryValidationError("Unsupported glossary link kind.")
    payload = {
        "kind": kind,
        "dataset_id": getattr(dataset, "id", None),
        "catalog": getattr(dataset, "catalog", None),
        "schema": getattr(dataset, "schema", None),
        "table": getattr(dataset, "table_name", None),
        "sql": getattr(dataset, "sql", None),
        "database": connection_identity(getattr(dataset, "database", None)),
    }
    if kind == "column":
        payload["column"] = getattr(target, "column_name", None)
        payload["active"] = getattr(target, "is_active", None)
        payload["expression"] = getattr(target, "expression", None)
    elif kind == "metric":
        payload["metric_id"] = getattr(target, "id", None)
        payload["metric_name"] = getattr(target, "metric_name", None)
        payload["expression"] = getattr(target, "expression", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def live_fingerprint(link: GlossaryTermLink) -> str | None:
    dataset = get_dataset(link.dataset_id)
    if dataset is None:
        return None
    target = link_target(link, dataset)
    if link.kind != "dataset" and target is None:
        return None
    return link_fingerprint(dataset, link.kind, target)


def link_is_live(link: GlossaryTermLink) -> bool:
    if live_fingerprint(link) != link.fingerprint:
        return False
    if link.kind != "metric":
        return True
    dataset = get_dataset(link.dataset_id)
    return metric_approved(dataset, link_target(link, dataset))


def validated_links(
    links: list[dict[str, Any]],
    dataset_resolver: Callable[[int], Any],
    metric_is_approved: Callable[[Any, Any], bool],
) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for raw in links:
        dataset = dataset_resolver(raw["dataset_id"])
        if dataset is None:
            raise GlossaryValidationError("Invalid glossary link.")
        kind = raw["kind"]
        target = None
        if kind == "column":
            name = raw.get("column_name")
            target = next((column for column in dataset.columns if getattr(column, "column_name", None) == name), None)
            if target is None or getattr(target, "is_active", None) is not True or getattr(target, "expression", None):
                raise GlossaryValidationError("Invalid glossary link.")
        elif kind == "metric":
            metric_id = raw.get("metric_id")
            target = next((metric for metric in dataset.metrics if getattr(metric, "id", None) == metric_id), None)
            if target is None:
                raise GlossaryValidationError("Invalid glossary link.")
            if not metric_is_approved(dataset, target):
                raise GlossaryValidationError("A glossary term may link only approved metrics.")
        elif raw.get("column_name") is not None or raw.get("metric_id") is not None:
            raise GlossaryValidationError("Invalid glossary link.")
        values = {
            "kind": kind,
            "dataset_id": dataset.id,
            "column_name": getattr(target, "column_name", None),
            "metric_id": getattr(target, "id", None) if kind == "metric" else None,
            "link_key": f"{kind}:{dataset.id}:{getattr(target, 'column_name', '')}:{getattr(target, 'id', '')}",
            "fingerprint": link_fingerprint(dataset, kind, target),
        }
        key = (values["kind"], values["dataset_id"], values["column_name"], values["metric_id"])
        if key in seen:
            raise GlossaryValidationError("Duplicate glossary link.")
        seen.add(key)
        result.append(values)
    return result


# -------------------------ACCESS-------------------------
def revision_readable(revision_id: int) -> bool:
    for link in read_links(revision_id):
        dataset = get_dataset(link.dataset_id)
        if dataset is not None and not can_access_dataset(dataset):
            return False
    return True


def term_readable(term_id: int) -> bool:
    revision = glossary_revision_repository().read_current(term_id)
    return revision is None or revision_readable(revision.id)


def discoverable_glossary_terms() -> list[dict[str, Any]]:
    terms = []
    for revision in glossary_revision_repository().read_all_serving():
        visible_links = []
        for link in read_links(revision.id):
            dataset = get_dataset(link.dataset_id)
            if dataset is None or not can_access_dataset(dataset):
                continue
            target = link_target(link, dataset)
            if link.kind != "dataset" and target is None:
                continue
            if link_fingerprint(dataset, link.kind, target) != link.fingerprint:
                continue
            if link.kind == "metric" and not metric_approved(dataset, target):
                continue
            visible_links.append(
                {
                    "kind": link.kind,
                    "dataset_id": link.dataset_id,
                    "column_name": link.column_name,
                    "metric_id": link.metric_id,
                }
            )
        if not visible_links:
            continue
        group = revision.term.group
        terms.append(
            {
                "term_id": revision.term_id,
                "canonical_name": revision.term.canonical_name,
                # Terms of one group mean the same or nearly the same, so a consumer can read them together.
                "group": {"id": group.id, "name": group.name} if group else None,
                "definition": revision.definition,
                "synonyms": revision.synonyms or [],
                "links": visible_links,
            }
        )
    return terms
