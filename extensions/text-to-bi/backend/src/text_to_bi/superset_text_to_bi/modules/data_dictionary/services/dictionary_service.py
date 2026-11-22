from collections import defaultdict
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import (
    can_access_dataset,
    column_type,
    database_name,
    dataset_columns,
    dataset_kind,
    readable_datasets,
)

from ..exceptions import DataDictionaryValidationError
from ..models import (
    ColumnAggregation,
    ColumnDictionary,
    ColumnSynonym,
    IndicatorAggregation,
    TableColumnRole,
    TableDictionary,
    TableTimeGrain,
)
from ..repositories import (
    ColumnAggregationRepository,
    ColumnDictionaryRepository,
    ColumnSynonymRepository,
    IndicatorAggregationRepository,
    TableColumnRoleRepository,
    TableDictionaryRepository,
    TableTimeGrainRepository,
)
from . import semantics
from .srv_superset_catalog import SupersetCatalogService


def _text(value: str | None, field: str, max_length: int) -> str | None:
    if value is None or not value.strip():
        return None
    if len(value.strip()) > max_length:
        raise DataDictionaryValidationError(f"{field} tối đa {max_length} ký tự.")
    return value.strip()


def _required_text(value: str, field: str, max_length: int) -> str:
    text = _text(value, field, max_length)
    if text is None:
        raise DataDictionaryValidationError(f"{field} không được để trống.")
    return text


def _choice(value: str | None, field: str, choices: tuple[str, ...]) -> str | None:
    if value is not None and value not in choices:
        raise DataDictionaryValidationError(f"{field} phải là một trong: {', '.join(choices)}.")
    return value


def column_names(dataset: Any) -> set[str]:
    return {column.column_name for column in dataset_columns(dataset)}


def is_key(column_name: str, is_primary_key: bool | None, has_reference: bool) -> bool:
    if is_primary_key is not None:
        return is_primary_key or has_reference
    return has_reference or semantics.looks_like_key(column_name)


# Dictionary rows are created only when someone saves or autofills; a dataset or column without one is described with
# defaults taken from Superset's own metadata.
class DataDictionaryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.superset_catalog = SupersetCatalogService(session)
        self.table_dictionaries = TableDictionaryRepository(session)
        self.column_roles = TableColumnRoleRepository(session)
        self.time_grains = TableTimeGrainRepository(session)
        self.indicator_aggregations = IndicatorAggregationRepository(session)
        self.column_dictionaries = ColumnDictionaryRepository(session)
        self.column_aggregations = ColumnAggregationRepository(session)
        self.column_synonyms = ColumnSynonymRepository(session)

    # -------------------------READ---------------------------
    def get_dataset_dictionary(self, dataset: Any) -> dict[str, Any]:
        return self._describe(dataset)

    # The datasets the caller may read, grouped by database and schema.
    def get_summary(self) -> dict[str, Any]:
        entries = self._dataset_entries(readable_datasets())
        databases: dict[tuple[int | None, str], dict[str | None, list[dict[str, Any]]]] = {}
        for entry in entries:
            schemas = databases.setdefault((entry["database_id"], entry["database_name"]), {})
            schemas.setdefault(entry["schema_name"], []).append(entry)
        return {
            "table_count": len(entries),
            "described_table_count": sum(entry["is_saved"] for entry in entries),
            "databases": [
                {
                    "database_id": database_id,
                    "database_name": name,
                    "schemas": [{"schema_name": schema, "tables": tables} for schema, tables in schemas.items()],
                }
                for (database_id, name), schemas in databases.items()
            ],
        }

    def get_stats(self, limit: int) -> dict[str, Any]:
        datasets = readable_datasets()
        entries = self._dataset_entries(datasets)
        names = {dataset.id: column_names(dataset) for dataset in datasets}
        referencing: dict[int, set[int]] = defaultdict(set)
        for source_id, source_column, target_id, target_column in self.column_dictionaries.read_references(names):
            if (
                target_id in names and target_id != source_id and source_column in names[source_id]
                and target_column in names[target_id]
            ):
                referencing[target_id].add(source_id)

        schemas: dict[tuple[int | None, str, str | None], list[dict[str, Any]]] = {}
        for entry in entries:
            schemas.setdefault((entry["database_id"], entry["database_name"], entry["schema_name"]), []).append(entry)

        def ranked(key: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = [item for item in items if item[key] > 0]
            return sorted(
                items,
                key=lambda item: (-item[key], item["database_name"], item["schema_name"] or "", item["table_name"]),
            )[:limit]

        def ranking_entry(entry: dict[str, Any], **values: Any) -> dict[str, Any]:
            fields = ("dataset_id", "database_name", "schema_name", "table_name", "display_name", "is_saved")
            return {**{field: entry[field] for field in fields}, **values}

        return {
            "table_count": len(entries),
            "described_table_count": sum(entry["is_saved"] for entry in entries),
            "column_count": sum(entry["column_count"] for entry in entries),
            "described_column_count": sum(entry["described_column_count"] for entry in entries),
            "schemas": [
                {
                    "database_id": database_id,
                    "database_name": name,
                    "schema_name": schema,
                    "table_count": len(tables),
                    "described_table_count": sum(table["is_saved"] for table in tables),
                }
                for (database_id, name, schema), tables in schemas.items()
            ],
            "most_columns": ranked("column_count", [
                ranking_entry(
                    entry, column_count=entry["column_count"], described_column_count=entry["described_column_count"]
                )
                for entry in entries
            ]),
            "most_referenced": ranked("referencing_table_count", [
                ranking_entry(entry, referencing_table_count=len(referencing[entry["dataset_id"]])) for entry in entries
            ]),
        }

    # -------------------------UPDATE-------------------------
    def save_table_dictionary(self, dataset: Any, values: dict[str, Any]) -> dict[str, Any]:
        names = column_names(dataset)
        layout = _choice(values.get("layout", "wide"), "layout", semantics.LAYOUTS) or "wide"
        roles = self._checked_roles(values.get("column_roles", []), layout, names)
        has_row_kind = any(role["role"] == "row_kind" for role in roles)
        grains = self._checked_time_grains(values.get("time_grains", []), has_row_kind)
        aggregations = self._checked_indicator_aggregations(values.get("indicator_aggregations", []), layout, roles)
        fields = {
            "display_name": _required_text(values["display_name"], "display_name", 255),
            "description": _text(values.get("description"), "description", semantics.MAX_DESCRIPTION_LENGTH),
            "grain_description": _text(
                values.get("grain_description"), "grain_description", semantics.MAX_DESCRIPTION_LENGTH
            ),
            "table_kind": _choice(values.get("table_kind"), "table_kind", semantics.TABLE_KINDS),
            "layout": layout,
            "contains_pii": bool(values.get("contains_pii", False)),
            "indicator_catalog_id": self._checked_catalog(dataset, layout, values.get("indicator_catalog_dataset_id")),
        }

        dictionary = self.table_dictionaries.read_by_dataset_id(dataset.id)
        if dictionary is None:
            dictionary = self.table_dictionaries.create(TableDictionary(dataset_id=dataset.id, **fields))
        else:
            if dictionary.layout == "indicator_catalog" and layout != "indicator_catalog":
                self.table_dictionaries.clear_catalog_references(dictionary.id)
            self.table_dictionaries.update(dictionary, fields)

        self.column_roles.delete_by_parent_id(dictionary.id)
        self.time_grains.delete_by_parent_id(dictionary.id)
        self.indicator_aggregations.delete_by_parent_id(dictionary.id)
        self.column_roles.create_many(TableColumnRole(table_dictionary_id=dictionary.id, **role) for role in roles)
        self.time_grains.create_many(TableTimeGrain(table_dictionary_id=dictionary.id, **grain) for grain in grains)
        self.indicator_aggregations.create_many(
            IndicatorAggregation(table_dictionary_id=dictionary.id, **item) for item in aggregations
        )
        return self._describe(dataset)

    # Only the columns in the request change; each item is the column's whole dictionary.
    def save_column_dictionaries(self, dataset: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
        columns = {column.column_name: column for column in dataset_columns(dataset)}
        row_kind_names = self._row_kind_column_names(self.table_dictionaries.read_by_dataset_id(dataset.id))
        targets = self._reference_targets(dataset, items)
        stored = {entry.column_name: entry for entry in self.column_dictionaries.read_by_dataset_id(dataset.id)}

        checked = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            column = columns.get(item["column_name"])
            if column is None:
                raise DataDictionaryValidationError(f"columns[{index}].column_name không thuộc dataset này.")
            if column.column_name in seen:
                raise DataDictionaryValidationError(f"columns[{index}].column_name bị lặp.")
            seen.add(column.column_name)
            checked.append(self._checked_column(index, item, dataset, column, row_kind_names, targets))

        for column, fields, aggregations, synonyms in checked:
            entry = stored.get(column.column_name)
            if entry is None:
                entry = self.column_dictionaries.create(
                    ColumnDictionary(dataset_id=dataset.id, column_name=column.column_name, **fields)
                )
            else:
                self.column_dictionaries.update(entry, fields)
                self.column_aggregations.delete_by_parent_id(entry.id)
                self.column_synonyms.delete_by_parent_id(entry.id)
            self.column_aggregations.create_many(
                ColumnAggregation(column_dictionary_id=entry.id, aggregation=value) for value in aggregations
            )
            self.column_synonyms.create_many(
                ColumnSynonym(column_dictionary_id=entry.id, synonym=value) for value in synonyms
            )
        return self._describe(dataset)

    # -------------------------HELPERS------------------------
    def _dataset_entries(self, datasets: list[Any]) -> list[dict[str, Any]]:
        dataset_ids = [dataset.id for dataset in datasets]
        dictionaries = {entry.dataset_id: entry for entry in self.table_dictionaries.read_by_dataset_ids(dataset_ids)}
        saved: dict[int, set[str]] = defaultdict(set)
        for dataset_id, column_name in self.column_dictionaries.read_saved_names(dataset_ids):
            saved[dataset_id].add(column_name)
        entries = []
        for dataset in datasets:
            names = column_names(dataset)
            dictionary = dictionaries.get(dataset.id)
            entries.append({
                "dataset_id": dataset.id,
                "database_id": getattr(dataset, "database_id", None),
                "database_name": database_name(dataset),
                "schema_name": dataset.schema,
                "table_name": dataset.table_name,
                "dataset_kind": dataset_kind(dataset),
                "is_saved": dictionary is not None,
                "display_name": dictionary.display_name if dictionary else dataset.table_name,
                "layout": dictionary.layout if dictionary else "wide",
                "column_count": len(names),
                "described_column_count": len(names & saved[dataset.id]),
            })
        return entries

    def _row_kind_column_names(self, dictionary: TableDictionary | None) -> set[str]:
        if dictionary is None:
            return set()
        roles = self.column_roles.read_by_parent_ids([dictionary.id])
        return {role.column_name for role in roles if role.role == "row_kind"}

    def _checked_roles(self, items: list[dict[str, Any]], layout: str, names: set[str]) -> list[dict[str, Any]]:
        allowed = semantics.LAYOUT_ROLES[layout]
        roles = []
        seen: set[tuple[str, str | None]] = set()
        for index, item in enumerate(items):
            role, qualifier, column_name = item["role"], item.get("qualifier"), item["column_name"]
            if role not in allowed:
                raise DataDictionaryValidationError(
                    f"column_roles[{index}].role với layout {layout} phải là một trong: {', '.join(allowed)}."
                )
            if role == "value":
                _choice(qualifier, f"column_roles[{index}].qualifier", semantics.VALUE_KINDS)
                if qualifier is None:
                    raise DataDictionaryValidationError(f"column_roles[{index}].qualifier cần kiểu giá trị.")
            elif qualifier is not None:
                raise DataDictionaryValidationError(f"column_roles[{index}].qualifier chỉ dùng với vai trò value.")
            if column_name not in names:
                raise DataDictionaryValidationError(f"column_roles[{index}].column_name không thuộc dataset này.")
            if (role, qualifier) in seen:
                raise DataDictionaryValidationError(f"column_roles[{index}] gán trùng vai trò {role}.")
            seen.add((role, qualifier))
            roles.append({"role": role, "qualifier": qualifier, "column_name": column_name})

        assigned = {role["role"] for role in roles}
        if missing := [role for role in semantics.REQUIRED_ROLES[layout] if role not in assigned]:
            raise DataDictionaryValidationError(f"Layout {layout} cần các vai trò: {', '.join(missing)}.")
        indicator_columns = {role["column_name"] for role in roles if role["role"] == "indicator_key"}
        if any(role["role"] == "value" and role["column_name"] in indicator_columns for role in roles):
            raise DataDictionaryValidationError("Cột chỉ số không thể đồng thời là cột giá trị.")
        return roles

    def _checked_time_grains(self, items: list[dict[str, Any]], has_row_kind: bool) -> list[dict[str, Any]]:
        grains = []
        seen: set[str | None] = set()
        for index, item in enumerate(items):
            row_kind_value = _text(item.get("row_kind_value"), f"time_grains[{index}].row_kind_value", 255)
            if has_row_kind and row_kind_value is None:
                raise DataDictionaryValidationError(f"time_grains[{index}].row_kind_value không được để trống.")
            if not has_row_kind and row_kind_value is not None:
                raise DataDictionaryValidationError(
                    f"time_grains[{index}].row_kind_value cần một cột có vai trò row_kind."
                )
            if row_kind_value in seen:
                raise DataDictionaryValidationError(f"time_grains[{index}] bị lặp loại dòng.")
            seen.add(row_kind_value)
            grains.append({
                "row_kind_value": row_kind_value,
                "label": _text(item.get("label"), f"time_grains[{index}].label", 255),
                "time_grain": _choice(item["time_grain"], f"time_grains[{index}].time_grain", semantics.TIME_GRAINS),
            })
        return grains

    def _checked_indicator_aggregations(
        self, items: list[dict[str, Any]], layout: str, roles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not items:
            return []
        if layout != "indicator_catalog" or not any(role["role"] == "catalog_aggregation" for role in roles):
            raise DataDictionaryValidationError(
                "indicator_aggregations chỉ dùng cho bảng danh mục chỉ số có cột vai trò catalog_aggregation."
            )
        if len(items) > semantics.MAX_INDICATOR_CODES:
            raise DataDictionaryValidationError(f"indicator_aggregations tối đa {semantics.MAX_INDICATOR_CODES} mã.")
        checked = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            source_code = _required_text(item["source_code"], f"indicator_aggregations[{index}].source_code", 64)
            if source_code in seen:
                raise DataDictionaryValidationError(f"indicator_aggregations[{index}].source_code bị lặp.")
            seen.add(source_code)
            aggregation = _choice(
                item["aggregation"], f"indicator_aggregations[{index}].aggregation", semantics.INDICATOR_AGGREGATIONS
            )
            checked.append({"source_code": source_code, "aggregation": aggregation})
        return checked

    # The catalog must be a dataset the caller can read, on the same database, saved with layout indicator_catalog.
    def _checked_catalog(self, dataset: Any, layout: str, catalog_dataset_id: int | None) -> UUID | None:
        if catalog_dataset_id is None:
            return None
        if layout != "indicator_values":
            raise DataDictionaryValidationError("indicator_catalog_dataset_id chỉ dùng cho layout indicator_values.")
        if catalog_dataset_id == dataset.id:
            raise DataDictionaryValidationError("Dataset không thể là danh mục chỉ số của chính nó.")
        catalog_dataset = self.superset_catalog.dataset(catalog_dataset_id)
        catalog = self.table_dictionaries.read_by_dataset_id(catalog_dataset_id) if catalog_dataset else None
        if (
            catalog is None or catalog.layout != "indicator_catalog"
            or catalog_dataset.database_id != dataset.database_id or not can_access_dataset(catalog_dataset)
        ):
            raise DataDictionaryValidationError(
                "indicator_catalog_dataset_id phải là dataset cùng database đã được mô tả với layout indicator_catalog."
            )
        return catalog.id

    # Referenced datasets the caller can read on the dataset's own database, looked up once for the whole request.
    def _reference_targets(self, dataset: Any, items: list[dict[str, Any]]) -> dict[int, Any]:
        wanted = {item["referenced_column"]["dataset_id"] for item in items if item.get("referenced_column")}
        targets = {dataset.id: dataset} if dataset.id in wanted else {}
        for target in self.superset_catalog.datasets_by_ids(wanted - {dataset.id}):
            if target.database_id == dataset.database_id and can_access_dataset(target):
                targets[target.id] = target
        return targets

    def _checked_column(
        self, index: int, item: dict[str, Any], dataset: Any, column: Any, row_kind_names: set[str],
        targets: dict[int, Any],
    ) -> tuple[Any, dict[str, Any], list[str], list[str]]:
        prefix = f"columns[{index}]"
        temporal_kind = _choice(item.get("temporal_kind"), f"{prefix}.temporal_kind", semantics.TEMPORAL_KINDS)
        semantic_role = _choice(item.get("semantic_role"), f"{prefix}.semantic_role", semantics.SEMANTIC_ROLES)
        is_primary_key = item.get("is_primary_key")
        reference = item.get("referenced_column")
        effective_role = semantic_role or semantics.default_semantic_role(
            column_type(column), temporal_kind,
            is_key=is_key(column.column_name, is_primary_key, reference is not None),
            is_row_kind=column.column_name in row_kind_names,
        )
        if reference is not None:
            if reference["dataset_id"] == dataset.id and reference["column_name"] == column.column_name:
                raise DataDictionaryValidationError(f"{prefix}.referenced_column không được trỏ vào chính cột đó.")
            target = targets.get(reference["dataset_id"])
            if target is None or reference["column_name"] not in column_names(target):
                raise DataDictionaryValidationError(
                    f"{prefix}.referenced_column không tồn tại trong một dataset cùng database mà bạn đọc được."
                )

        aggregations = list(dict.fromkeys(item.get("aggregations", [])))
        for value in aggregations:
            _choice(value, f"{prefix}.aggregations", semantics.COLUMN_AGGREGATIONS)
        if aggregations and effective_role != "measure":
            raise DataDictionaryValidationError(f"{prefix}.aggregations chỉ dùng cho cột có vai trò measure.")

        fields = {
            "display_name": _required_text(item["display_name"], f"{prefix}.display_name", 255),
            "description": _text(item.get("description"), f"{prefix}.description", semantics.MAX_DESCRIPTION_LENGTH),
            "business_term": _text(
                item.get("business_term"), f"{prefix}.business_term", semantics.MAX_DESCRIPTION_LENGTH
            ),
            "semantic_role": semantic_role,
            "temporal_kind": temporal_kind,
            "unit": _text(item.get("unit"), f"{prefix}.unit", 128),
            "format": _text(item.get("format"), f"{prefix}.format", 128),
            "is_primary_key": is_primary_key,
            "is_unique": bool(item.get("is_unique", False)),
            "referenced_dataset_id": reference["dataset_id"] if reference else None,
            "referenced_column_name": reference["column_name"] if reference else None,
            "contains_pii": bool(item.get("contains_pii", False)),
        }
        return column, fields, aggregations, self._checked_synonyms(prefix, item.get("synonyms", []))

    @staticmethod
    def _checked_synonyms(prefix: str, values: Iterable[str]) -> list[str]:
        synonyms: dict[str, str] = {}
        for value in values:
            synonym = _text(value, f"{prefix}.synonyms", semantics.MAX_SYNONYM_LENGTH)
            if synonym is not None:
                synonyms.setdefault(synonym.casefold(), synonym)
        if len(synonyms) > semantics.MAX_SYNONYMS:
            raise DataDictionaryValidationError(f"{prefix}.synonyms tối đa {semantics.MAX_SYNONYMS} từ.")
        return list(synonyms.values())

    def _describe(self, dataset: Any) -> dict[str, Any]:
        columns = dataset_columns(dataset)
        names = {column.column_name for column in columns}
        dictionary = self.table_dictionaries.read_by_dataset_id(dataset.id)
        dictionary_ids = [dictionary.id] if dictionary else []
        # A role or a dictionary entry whose column Superset no longer has stays stored but is not shown; it comes
        # back when a column of that name does.
        roles = [role for role in self.column_roles.read_by_parent_ids(dictionary_ids) if role.column_name in names]
        row_kind_names = {role.column_name for role in roles if role.role == "row_kind"}

        entries = {
            entry.column_name: entry for entry in self.column_dictionaries.read_by_dataset_id(dataset.id)
            if entry.column_name in names
        }
        aggregations: dict[UUID, list[str]] = defaultdict(list)
        for row in self.column_aggregations.read_by_parent_ids(entry.id for entry in entries.values()):
            aggregations[row.column_dictionary_id].append(row.aggregation)
        synonyms: dict[UUID, list[str]] = defaultdict(list)
        for row in self.column_synonyms.read_by_parent_ids(entry.id for entry in entries.values()):
            synonyms[row.column_dictionary_id].append(row.synonym)
        references = self._column_references(entries.values())

        return {
            "dataset_id": dataset.id,
            "database_id": getattr(dataset, "database_id", None),
            "database_name": database_name(dataset),
            "schema_name": dataset.schema,
            "table_name": dataset.table_name,
            "dataset_kind": dataset_kind(dataset),
            "is_saved": dictionary is not None,
            "display_name": dictionary.display_name if dictionary else dataset.table_name,
            "description": dictionary.description if dictionary else dataset.description,
            "grain_description": dictionary.grain_description if dictionary else None,
            "table_kind": dictionary.table_kind if dictionary else None,
            "layout": dictionary.layout if dictionary else "wide",
            "indicator_catalog": self._indicator_catalog(dictionary),
            "contains_pii": dictionary.contains_pii if dictionary else False,
            "updated_at": dictionary.updated_at if dictionary else None,
            "column_roles": [
                {"role": role.role, "qualifier": role.qualifier, "column_name": role.column_name} for role in roles
            ],
            "time_grains": [
                {"row_kind_value": grain.row_kind_value, "label": grain.label, "time_grain": grain.time_grain}
                for grain in self.time_grains.read_by_parent_ids(dictionary_ids)
            ],
            "indicator_aggregations": [
                {"source_code": item.source_code, "aggregation": item.aggregation}
                for item in self.indicator_aggregations.read_by_parent_ids(dictionary_ids)
            ],
            "columns": [
                self._describe_column(
                    column, entries.get(column.column_name), row_kind_names, aggregations, synonyms, references
                )
                for column in columns
            ],
        }

    @staticmethod
    def _describe_column(
        column: Any,
        entry: ColumnDictionary | None,
        row_kind_names: set[str],
        aggregations: dict[UUID, list[str]],
        synonyms: dict[UUID, list[str]],
        references: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        data_type = column_type(column)
        is_dttm = bool(getattr(column, "is_dttm", False))
        temporal_kind = entry.temporal_kind if entry else semantics.default_temporal_kind(data_type, is_dttm)
        has_reference = column.column_name in references
        key = is_key(column.column_name, entry.is_primary_key if entry else None, has_reference)
        semantic_role = (entry.semantic_role if entry else None) or semantics.default_semantic_role(
            data_type, temporal_kind, is_key=key, is_row_kind=column.column_name in row_kind_names
        )
        verbose_name = getattr(column, "verbose_name", None) or None
        return {
            "column_name": column.column_name,
            "verbose_name": verbose_name,
            "data_type": data_type,
            "is_dttm": is_dttm,
            "is_calculated": bool(getattr(column, "expression", None)),
            "is_saved": entry is not None,
            "display_name": entry.display_name if entry else verbose_name or column.column_name,
            "description": entry.description if entry else getattr(column, "description", None),
            "business_term": entry.business_term if entry else None,
            "semantic_role": semantic_role,
            "semantic_role_is_default": not (entry and entry.semantic_role),
            "temporal_kind": temporal_kind,
            "unit": entry.unit if entry else None,
            "format": entry.format if entry else None,
            "is_primary_key": entry.is_primary_key if entry else None,
            "is_unique": entry.is_unique if entry else False,
            "referenced_column": references.get(column.column_name),
            "contains_pii": entry.contains_pii if entry else False,
            "aggregations": aggregations.get(entry.id, []) if entry else [],
            "synonyms": synonyms.get(entry.id, []) if entry else [],
            "updated_at": entry.updated_at if entry else None,
        }

    # Saved references by column name; one whose dataset or column is gone, or that the caller cannot read, is None.
    def _column_references(self, entries: Iterable[ColumnDictionary]) -> dict[str, dict[str, Any]]:
        referring = [entry for entry in entries if entry.referenced_dataset_id and entry.referenced_column_name]
        target_datasets = self.superset_catalog.datasets_by_ids(
            {entry.referenced_dataset_id for entry in referring}
        )
        targets = {target.id: target for target in target_datasets if can_access_dataset(target)}
        references = {}
        for entry in referring:
            target = targets.get(entry.referenced_dataset_id)
            if target is None or entry.referenced_column_name not in column_names(target):
                continue
            references[entry.column_name] = {
                "dataset_id": target.id,
                "schema_name": target.schema,
                "table_name": target.table_name,
                "column_name": entry.referenced_column_name,
            }
        return references

    def _indicator_catalog(self, dictionary: TableDictionary | None) -> dict[str, Any] | None:
        if dictionary is None or dictionary.indicator_catalog_id is None:
            return None
        catalog = self.table_dictionaries.read_by_id(dictionary.indicator_catalog_id)
        catalog_dataset = self.superset_catalog.dataset(catalog.dataset_id) if catalog else None
        if catalog_dataset is None or not can_access_dataset(catalog_dataset):
            return None
        return {
            "dataset_id": catalog_dataset.id,
            "schema_name": catalog_dataset.schema,
            "table_name": catalog_dataset.table_name,
            "display_name": catalog.display_name,
        }
