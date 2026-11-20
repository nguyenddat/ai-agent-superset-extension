import hashlib
import json
import logging
from typing import Any

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_login import current_user
from superset import db
from superset.connectors.sqla.models import SqlaTable, SqlMetric

from text_to_bi.superset_semantic_layer.common.public import public_payload
from text_to_bi.superset_semantic_layer.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_semantic_layer.core.routing import RouteMixin
from text_to_bi.superset_semantic_layer.core.security import (
    can_access_dataset,
    csrf_protected,
    require_admin,
    require_dataset_access,
    require_semantic_layer_query,
)
from text_to_bi.superset_semantic_layer.migrations import ensure_dictionary_tables
from text_to_bi.superset_semantic_layer.modules.business_model.dependencies import lineage_edge_repository
from text_to_bi.superset_semantic_layer.modules.business_model.models import LineageEdge
from text_to_bi.superset_semantic_layer.modules.metric_management.services.srv_metric_contract import (
    MetricContractService,
)
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import (
    dataset_for_creation_key,
    get_datasets,
    is_internal_dataset,
)

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository
from ..exceptions import (
    DatasetDraftValidationError,
    ProposedDatasetCreationError,
)
from ..models import ColumnDictionary
from ..services.srv_dataset_draft import (
    AGGREGATE_DATASET,
    BASE_DATASET,
    checked_dataset_proposal,
    derived_column_keys,
)
from ..services.srv_seeding import seed_dictionary

logger = logging.getLogger(__name__)



class DatasetDraftRoutes(RouteMixin):
    def _base_datasets(self, for_agent: bool) -> dict[str, SqlaTable]:
        base_ids = [row.id for row in dataset_dictionary_repository().read_by_type(BASE_DATASET)]
        datasets = get_datasets(base_ids)
        allowed = {}
        for dataset in datasets:
            if is_internal_dataset(dataset) or (for_agent and not can_access_dataset(dataset)):
                continue
            try:
                # This SQLAlchemy backref contains every rule attached to the table, independent of the current role.
                # Do not use security_manager.get_rls_filters here: it returns only rules applicable to this caller.
                if dataset.row_level_security_filters:
                    continue
            except Exception:
                logger.warning(
                    "Could not inspect attached RLS for draft source dataset %s; excluding it",
                    dataset.id, exc_info=True
                )
                continue
            allowed[dataset.table_name] = dataset
        return allowed

    @staticmethod
    def _carry_column_keys(dataset: SqlaTable, values: dict[str, Any], base_datasets: dict[str, SqlaTable]) -> None:
        sources = [dataset for dataset in base_datasets.values() if dataset.id in values["source_dataset_ids"]]
        entries: dict[int, dict[str, ColumnDictionary]] = {}
        column_repository = column_dictionary_repository()
        for entry in column_repository.read_by_datasets(values["source_dataset_ids"]):
            entries.setdefault(entry.dataset_id, {})[entry.column_name] = entry
        derived = derived_column_keys(values["sql"], sources, entries)
        for entry in column_repository.read_by_dataset(dataset.id):
            keys = derived.get(entry.column_name)
            if keys is None:
                continue
            referenced = entries[keys.referenced[0]][keys.referenced[1]]
            entry.is_pk, entry.is_unique = keys.is_pk, keys.is_unique
            entry.is_fk, entry.referenced_column = True, referenced.id
        referenced_sources = {keys.referenced[0] for keys in derived.values()}
        for source in sources:
            if source.id not in referenced_sources:
                edge = LineageEdge(source_dataset_id=source.id, target_dataset_id=dataset.id, kind="flow")
                lineage_edge_repository().add(edge, flush=False)

    @expose("/dataset-drafts/create", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_dataset_draft(self):
        require_admin()
        ensure_dictionary_tables()
        base_datasets = self._base_datasets(for_agent=False)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise DatasetDraftValidationError("Body phải là một JSON object.")
        creation_key = body.get("creation_key")
        if (
            not isinstance(creation_key, str) or not creation_key.startswith("ai-agent:dataset-proposal:")
            or len(creation_key) > 128
        ):
            raise DatasetDraftValidationError("Khóa tạo dataset không hợp lệ.")
        payload_hash = hashlib.sha256(json.dumps(
            {field: body.get(field) for field in ("name", "label", "description", "sql", "metric", "question")},
            sort_keys=True, ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        values = checked_dataset_proposal(body, base_datasets)
        existing = dataset_for_creation_key(creation_key)
        if existing is not None:
            require_dataset_access(existing)
            if json.loads(existing.extra or "{}").get("text_to_bi_creation_payload") != payload_hash:
                raise DatasetDraftValidationError(
                    "Đề xuất đã tạo dataset với nội dung khác; tải lại trang để kiểm tra."
                )
            if json.loads(existing.extra or "{}").get("text_to_bi_creation_ready", True):
                return self.response(200, **public_payload({'dataset_id': existing.id}))
        proposer_id = body.get("proposer_id") or current_user.id
        if isinstance(proposer_id, bool) or not isinstance(proposer_id, int):
            raise DatasetDraftValidationError("Người đề xuất không hợp lệ.")
        from superset.commands.dataset.create import CreateDatasetCommand
        from superset.commands.dataset.exceptions import DatasetCreateFailedError, DatasetInvalidError

        try:
            dataset = existing or CreateDatasetCommand(
                {
                    "database": values["database_id"],
                    "schema": values["schema"],
                    "table_name": values["name"],
                    "sql": values["sql"],
                    "owners": [current_user.id],
                    "extra": json.dumps({
                        "text_to_bi_creation_key": creation_key, "text_to_bi_creation_payload": payload_hash,
                        "text_to_bi_creation_ready": False,
                    }),
                }
            ).run()
        except DatasetInvalidError as ex:
            raise ProposedDatasetCreationError(f"Superset không tạo được dataset: {ex.normalized_messages()}") from ex
        except DatasetCreateFailedError as ex:
            logger.exception("Creating the proposed dataset %s failed", values["name"])
            raise ProposedDatasetCreationError() from ex
        seed_dictionary(dataset)
        dictionary = dataset_dictionary_repository().read(dataset.id)
        dictionary.display_name = values["label"]
        dictionary.description = values["description"]
        dictionary.dataset_type = AGGREGATE_DATASET
        self._carry_column_keys(dataset, values, base_datasets)
        metric_values = values["metric"]
        metric = SqlMetric(
            metric_name=metric_values["metric_name"],
            verbose_name=metric_values["label"],
            expression=metric_values["expression"],
            description=metric_values["definition"],
        )
        dataset.metrics.append(metric)
        db.session.flush()
        MetricContractService().propose_for_agent(
            dataset, metric, metric_values["definition"], metric_values["unit"], "AI Agent dataset draft", proposer_id
        )
        dataset.extra = json.dumps({
            **json.loads(dataset.extra or "{}"), "text_to_bi_creation_key": creation_key,
            "text_to_bi_creation_payload": payload_hash, "text_to_bi_creation_ready": True,
        })
        db.session.commit()
        return self.response(201, **public_payload({'dataset_id': dataset.id}))

    @expose("/dataset-drafts/validate", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def validate_dataset_draft(self):
        require_semantic_layer_query()
        ensure_dictionary_tables()
        values = checked_dataset_proposal(request.get_json(silent=True), self._base_datasets(for_agent=True))
        return self.response(200, **public_payload({'draft': values}))
