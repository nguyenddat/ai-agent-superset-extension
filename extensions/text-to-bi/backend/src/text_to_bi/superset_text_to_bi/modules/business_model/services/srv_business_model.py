import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import require_edit
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import TableDictionary
from text_to_bi.superset_text_to_bi.modules.data_dictionary.repositories import (
    SupersetDatabaseRepository,
    SupersetDatasetRepository,
    TableDictionaryRepository,
)
from text_to_bi.superset_text_to_bi.modules.data_lineage.services.srv_data_lineage import DataLineageService

from ..exceptions import BusinessModelConflictError, BusinessModelNotFoundError, BusinessModelValidationError
from ..models import BusinessCanvas, BusinessDomain, DataLayer
from ..repositories import (
    BusinessCanvasRepository,
    BusinessDomainRepository,
    DataLayerRepository,
    DatasetLayerRepository,
)

COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}\Z")

def _name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 255:
        raise BusinessModelValidationError("Name must contain between 1 and 255 characters.")
    return value

def _color(value: str | None) -> str | None:
    if value is not None and not COLOR_PATTERN.fullmatch(value):
        raise BusinessModelValidationError("Color must use #RRGGBB format.")
    return value

class BusinessModelService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.layers = DataLayerRepository(session)
        self.domains = BusinessDomainRepository(session)
        self.canvases = BusinessCanvasRepository(session)
        self.dataset_layers = DatasetLayerRepository(session)
        self.dictionaries = TableDictionaryRepository(session)
        self.databases = SupersetDatabaseRepository(session)
        self.datasets = SupersetDatasetRepository(session)
        self.lineage = DataLineageService(session)

    def list_layers(self) -> list[DataLayer]:
        return self.layers.ordered()

    def create_layer(self, values: dict[str, Any]) -> DataLayer:
        name = _name(values["name"])
        if self.layers.by_name(name):
            raise BusinessModelConflictError()
        layer = DataLayer(
            name=name, description=values.get("description"), color=_color(values.get("color")),
            level=values.get("level", 0), sort_order=values.get("sort_order", 0),
        )
        try:
            return self.layers.create(layer)
        except IntegrityError:
            raise BusinessModelConflictError() from None

    def update_layer(self, layer_id: UUID, values: dict[str, Any]) -> DataLayer:
        layer = self._layer(layer_id)
        name = _name(values["name"])
        other = self.layers.by_name(name)
        if other and other.id != layer_id:
            raise BusinessModelConflictError()
        try:
            return self.layers.update(layer, {
                "name": name, "description": values.get("description"), "color": _color(values.get("color")),
                "level": values.get("level", 0), "sort_order": values.get("sort_order", 0),
            })
        except IntegrityError:
            raise BusinessModelConflictError() from None

    def delete_layer(self, layer_id: UUID) -> None:
        self.layers.delete(self._layer(layer_id))

    def reorder_layers(self, levels: list[list[UUID]]) -> list[DataLayer]:
        layers = self.layers.ordered()
        ordered = [item for group in levels for item in group]
        if len(ordered) != len(set(ordered)) or set(ordered) != {item.id for item in layers}:
            raise BusinessModelValidationError("Order must contain every layer exactly once.")
        by_id = {item.id: item for item in layers}
        for level, group in enumerate(levels):
            for order, layer_id in enumerate(group):
                by_id[layer_id].level, by_id[layer_id].sort_order = level, order
        self.session.flush()
        return self.layers.ordered()

    def list_domains(
        self, database_id: int | None = None, allowed_dataset_ids: set[int] | None = None
    ) -> list[dict[str, Any]]:
        dataset_ids = [item.id for item in self.datasets.read_by_database_id(database_id)] if database_id else None
        if allowed_dataset_ids is not None:
            dataset_ids = [
                dataset_id for dataset_id in (dataset_ids or allowed_dataset_ids)
                if dataset_id in allowed_dataset_ids
            ]
        memberships = self.domains.memberships(dataset_ids)
        return [
            {
                "id": item.id, "name": item.name, "description": item.description, "color": item.color,
                "dataset_ids": memberships.get(item.id, []),
            }
            for item in self.domains.ordered()
        ]

    def create_domain(self, values: dict[str, Any]) -> dict[str, Any]:
        name = _name(values["name"])
        if self.domains.by_name(name):
            raise BusinessModelConflictError()
        dataset_ids = self._valid_dataset_ids(values.get("dataset_ids", []))
        dictionary_ids = self._dictionary_ids(dataset_ids)
        domain = BusinessDomain(name=name, description=values.get("description"), color=_color(values.get("color")))
        try:
            self.domains.create(domain)
        except IntegrityError:
            raise BusinessModelConflictError() from None
        self.domains.replace_memberships(domain.id, dictionary_ids)
        return {
            "id": domain.id, "name": domain.name, "description": domain.description,
            "color": domain.color, "dataset_ids": dataset_ids,
        }

    def update_domain(self, domain_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        domain = self._domain(domain_id)
        name = _name(values["name"])
        other = self.domains.by_name(name)
        if other and other.id != domain_id:
            raise BusinessModelConflictError()
        dataset_ids = self._valid_dataset_ids(values.get("dataset_ids", []))
        dictionary_ids = self._dictionary_ids(dataset_ids)
        try:
            self.domains.update(domain, {
                "name": name, "description": values.get("description"), "color": _color(values.get("color")),
            })
        except IntegrityError:
            raise BusinessModelConflictError() from None
        self.domains.replace_memberships(domain.id, dictionary_ids)
        return {
            "id": domain.id, "name": domain.name, "description": domain.description,
            "color": domain.color, "dataset_ids": dataset_ids,
        }

    def delete_domain(self, domain_id: UUID) -> None:
        self.domains.delete(self._domain(domain_id))

    def assign_layer(self, dataset_id: int, layer_id: UUID | None) -> dict[str, Any]:
        dataset = self.datasets.read_by_id(dataset_id)
        if dataset is None:
            raise BusinessModelNotFoundError()
        require_edit(dataset)
        if layer_id is not None:
            self._layer(layer_id)
        row = self.dataset_layers.by_dataset(dataset_id)
        if row is None:
            if layer_id is not None:
                self.dataset_layers.create(self.dataset_layers.model(dataset_id=dataset_id, layer_id=layer_id))
        elif layer_id is None:
            self.dataset_layers.delete(row)
        else:
            row.layer_id = layer_id
            self.session.flush()
        return {"dataset_id": dataset_id, "layer_id": layer_id}

    def get_model(self, database_id: int, datasets: list[Any]) -> dict[str, Any]:
        database = self.databases.read_by_id(database_id)
        if database is None:
            raise BusinessModelNotFoundError("Database not found.")
        ids = [dataset.id for dataset in datasets]
        dictionary_rows = self.dictionaries.read_by_dataset_ids(ids)
        dictionary_by_dataset = {row.dataset_id: row for row in dictionary_rows}
        assignments = self.dataset_layers.by_datasets(ids)
        domains = self.list_domains(database_id, allowed_dataset_ids=set(ids))
        business_canvas = self.canvases.by_database(database_id)
        return {
            "database_id": database_id,
            "layers": self.layers.ordered(),
            "domains": domains,
            "datasets": [
                {
                    "dataset_id": dataset.id, "schema": dataset.schema, "table_name": dataset.table_name,
                    "display_name": (dictionary_by_dataset[dataset.id].display_name
                                     if dataset.id in dictionary_by_dataset else dataset.table_name),
                    "table_kind": (dictionary_by_dataset[dataset.id].table_kind
                                   if dataset.id in dictionary_by_dataset else None),
                    "layer_id": assignments[dataset.id].layer_id if dataset.id in assignments else None,
                    "is_classified": dataset.id in dictionary_by_dataset,
                }
                for dataset in datasets
            ],
            "business_canvas": json.loads(business_canvas.layout) if business_canvas else {},
            "lineage": self.lineage.graph(database_id, datasets),
        }

    def save_canvas(self, database_id: int, layout: dict[str, Any]) -> BusinessCanvas:
        if self.databases.read_by_id(database_id) is None:
            raise BusinessModelNotFoundError("Database not found.")
        row = self.canvases.by_database(database_id)
        encoded = json.dumps(layout, separators=(",", ":"))
        if row is None:
            return self.canvases.create(BusinessCanvas(database_id=database_id, layout=encoded))
        return self.canvases.update(row, {"layout": encoded})

    def _layer(self, layer_id: UUID) -> DataLayer:
        row = self.layers.read_by_id(layer_id)
        if row is None:
            raise BusinessModelNotFoundError("Data layer not found.")
        return row

    def _domain(self, domain_id: UUID) -> BusinessDomain:
        row = self.domains.read_by_id(domain_id)
        if row is None:
            raise BusinessModelNotFoundError("Business domain not found.")
        return row

    def _valid_dataset_ids(self, dataset_ids: list[int]) -> list[int]:
        unique_ids = list(dict.fromkeys(dataset_ids))
        datasets = self.datasets.read_by_ids(unique_ids)
        if len(datasets) != len(unique_ids):
            raise BusinessModelValidationError("Unknown dataset in membership list.")
        for dataset in datasets:
            require_edit(dataset)
        return unique_ids

    def _dictionary_ids(self, dataset_ids: list[int]) -> list[UUID]:
        dictionary_rows = self.dictionaries.read_by_dataset_ids(dataset_ids)
        dictionary_by_dataset = {row.dataset_id: row for row in dictionary_rows}
        for dataset_id in dataset_ids:
            if dataset_id not in dictionary_by_dataset:
                dataset = self.datasets.read_by_id(dataset_id)
                row = TableDictionary(dataset_id=dataset_id, display_name=dataset.table_name or str(dataset_id))
                dictionary_by_dataset[dataset_id] = self.dictionaries.create(row)
        return [dictionary_by_dataset[dataset_id].id for dataset_id in dataset_ids]
