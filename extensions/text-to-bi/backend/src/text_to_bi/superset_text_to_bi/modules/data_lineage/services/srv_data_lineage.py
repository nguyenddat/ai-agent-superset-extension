import json
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import require_dataset_access, require_edit
from text_to_bi.superset_text_to_bi.modules.data_dictionary.repositories import ColumnDictionaryRepository
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import (
    can_access_dataset,
    require_dataset,
)

from ..exceptions import DataLineageValidationError, LineageConflictError, LineageNotFoundError
from ..models import LineageCanvas, LineageEdge, LineageTransformation
from ..repositories import LineageCanvasRepository, LineageEdgeRepository, LineageTransformationRepository
from .sql_preview import preview_sql

EDGE_KINDS = ("flow", "relation", "transform")
MAX_SQL_BYTES = 1024 * 1024


class DataLineageService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.edges = LineageEdgeRepository(session)
        self.canvases = LineageCanvasRepository(session)
        self.transformations = LineageTransformationRepository(session)
        self.columns = ColumnDictionaryRepository(session)

    # -------------------------READ---------------------------
    def graph(self, database_id: int, datasets: Iterable[Any]) -> dict[str, Any]:
        visible = {dataset.id: dataset for dataset in datasets if can_access_dataset(dataset)}
        references = self.columns.read_references(visible)
        live_columns = {
            dataset_id: {str(column.column_name) for column in dataset.columns}
            for dataset_id, dataset in visible.items()
        }
        inferred: dict[tuple[int, int, str], dict[str, Any]] = {}
        for source_id, source_column, target_id, target_column in references:
            if source_id not in visible or target_id not in visible or source_id == target_id:
                continue
            # Dictionary references can outlive a Superset column that was deleted or renamed.
            if source_column not in live_columns[source_id] or target_column not in live_columns[target_id]:
                continue
            key = (source_id, target_id, "relation")
            edge = inferred.setdefault(key, {
                "source": source_id, "target": target_id, "kind": "relation", "origin": "dictionary",
                "label": None, "color": None, "columns": [],
            })
            edge["columns"].append({"source": source_column, "target": target_column})

        rows = self.edges.read_between(visible)
        by_key = {(row.source_dataset_id, row.target_dataset_id, row.kind): row for row in rows}
        for key, edge in list(inferred.items()):
            override = by_key.get(key)
            if override is not None:
                edge["color"] = override.color
                if override.is_hidden:
                    del inferred[key]
        transformation_edges = self._transformation_edges(visible)
        transformation_keys = {
            (edge["source"], edge["target"], edge["kind"]) for edge in transformation_edges
        }
        visible_transformations = []
        for edge in transformation_edges:
            key = (edge["source"], edge["target"], edge["kind"])
            override = by_key.get(key)
            if override is not None and override.is_hidden:
                continue
            if override is not None:
                edge["color"] = override.color
            visible_transformations.append(edge)
        for key, row in by_key.items():
            if row.is_manual and not row.is_hidden and key not in inferred and key not in transformation_keys:
                inferred[key] = {
                    "source": row.source_dataset_id, "target": row.target_dataset_id, "kind": row.kind,
                    "origin": "manual", "label": row.label, "color": row.color, "columns": [],
                }
        canvas = self.canvases.read_for_database(database_id)
        inferred.update({
            (edge["source"], edge["target"], edge["kind"]): edge for edge in visible_transformations
        })
        return {
            "database_id": database_id,
            "datasets": [
                {"id": dataset.id, "name": dataset.table_name, "schema": dataset.schema,
                 "description": dataset.description}
                for dataset in sorted(visible.values(), key=lambda item: (item.schema or "", item.table_name or ""))
            ],
            "edges": sorted(inferred.values(), key=lambda edge: (edge["source"], edge["target"], edge["kind"])),
            "canvas": json.loads(canvas.layout) if canvas else None,
        }

    def is_inferred(self, source_id: int, target_id: int, datasets: Iterable[Any]) -> bool:
        visible = {dataset.id: dataset for dataset in datasets}
        rows = self.columns.read_references(visible)
        live_columns = {
            dataset_id: {str(column.column_name) for column in dataset.columns}
            for dataset_id, dataset in visible.items()
        }
        return any(
            source_id == source and target_id == target and source != target
            and source_column in live_columns[source] and target_column in live_columns[target]
            for source, source_column, target, target_column in rows
            if source in live_columns and target in live_columns
        )

    def has_transformation(self, source_id: int, target_id: int) -> bool:
        return self.transformations.has_edge(source_id, target_id)

    def edge_override(self, source_id: int, target_id: int, kind: str) -> LineageEdge | None:
        direct = self.edges.read_key(source_id, target_id, kind)
        if direct is not None:
            return direct
        reverse = "relation" if kind == "flow" else "flow" if kind == "relation" else kind
        if reverse == kind:
            return None
        candidate = self.edges.read_key(target_id, source_id, reverse)
        if candidate is not None:
            candidate.source_dataset_id = source_id
            candidate.target_dataset_id = target_id
            candidate.kind = kind
        return candidate

    # -------------------------CREATE/UPDATE-----------------
    def save_canvas(self, database_id: int, layout_json: str) -> LineageCanvas:
        canvas = self.canvases.read_for_database(database_id)
        if canvas is None:
            canvas = LineageCanvas(database_id=database_id, layout=layout_json)
            self.session.add(canvas)
        else:
            canvas.layout = layout_json
        self.session.flush()
        return canvas

    def add_edge(self, source_id: int, target_id: int, kind: str) -> None:
        row = self.edge_override(source_id, target_id, kind)
        if row is None:
            row = LineageEdge(source_dataset_id=source_id, target_dataset_id=target_id, kind=kind)
            self.session.add(row)
        elif row.is_hidden:
            self.session.delete(row)
        else:
            row.is_manual = True
        self.session.flush()

    def set_edge_color(self, source_id: int, target_id: int, kind: str, color: str | None) -> None:
        row = self.edge_override(source_id, target_id, kind)
        if row is None:
            if color is not None:
                self.session.add(LineageEdge(
                    source_dataset_id=source_id, target_dataset_id=target_id, kind=kind,
                    color=color, is_manual=False,
                ))
        elif color is None and not row.is_manual and not row.is_hidden:
            self.session.delete(row)
        else:
            row.color = color
        self.session.flush()

    def remove_edge(self, source_id: int, target_id: int, kind: str, inferred: bool) -> None:
        if inferred:
            row = self.edge_override(source_id, target_id, kind)
            if row is None:
                self.session.add(LineageEdge(
                    source_dataset_id=source_id, target_dataset_id=target_id, kind=kind, is_hidden=True,
                ))
            else:
                row.is_hidden = True
        else:
            row = self.edge_override(source_id, target_id, kind)
            if row is not None:
                self.session.delete(row)
        self.session.flush()

    # -------------------------TRANSFORMATIONS--------------
    def list_transformations(self, database_id: int, datasets: Iterable[Any]) -> list[dict[str, Any]]:
        visible = {dataset.id: dataset for dataset in datasets if can_access_dataset(dataset)}
        rows = self.transformations.list_for_datasets(visible)
        inputs, dependencies = self.transformations.read_parts([row.id for row in rows])
        input_map: dict[UUID, list[int]] = {}
        dependency_map: dict[UUID, list[dict[str, Any]]] = {}
        for item in inputs:
            input_map.setdefault(item.transformation_id, []).append(item.source_dataset_id)
        for item in dependencies:
            dependency_map.setdefault(item.transformation_id, []).append({
                "source_dataset_id": item.source_dataset_id,
                "source_column_name": item.source_column_name,
                "target_column_name": item.target_column_name,
                "role": item.role,
            })
        return [
            self._transformation_out(row, input_map.get(row.id, []), dependency_map.get(row.id, []))
            for row in rows
            if row.target_dataset_id in visible
            and set(input_map.get(row.id, [])) <= visible.keys()
        ]

    def get_transformation(self, database_id: int, transformation_id: UUID, datasets: Iterable[Any]) -> dict[str, Any]:
        row = self.transformations.read(transformation_id)
        visible = {dataset.id: dataset for dataset in datasets if can_access_dataset(dataset)}
        if row is None or row.target_dataset_id not in visible:
            raise LineageNotFoundError()
        inputs, dependencies = self.transformations.read_parts([row.id])
        source_ids = [item.source_dataset_id for item in inputs]
        if not set(source_ids) <= visible.keys():
            raise LineageNotFoundError()
        return self._transformation_out(row, source_ids, [{
            "source_dataset_id": item.source_dataset_id, "source_column_name": item.source_column_name,
            "target_column_name": item.target_column_name, "role": item.role,
        } for item in dependencies])

    def save_transformation(
        self, values: dict[str, Any], datasets: Iterable[Any], transformation_id: UUID | None = None,
    ) -> dict[str, Any]:
        visible = {dataset.id: dataset for dataset in datasets if can_access_dataset(dataset)}
        target_id = values["target_dataset_id"]
        source_ids = values["source_dataset_ids"]
        if (
            target_id not in visible or not source_ids or target_id in source_ids
            or len(source_ids) != len(set(source_ids))
        ):
            raise DataLineageValidationError("Dataset đích và danh sách dataset nguồn phải hợp lệ.")
        if set(source_ids) - visible.keys():
            raise DataLineageValidationError("Dataset nguồn không thuộc phạm vi database hoặc không được phép xem.")
        target = visible[target_id]
        source_datasets = [visible[dataset_id] for dataset_id in source_ids]
        require_edit(target)
        for dataset in source_datasets:
            require_edit(dataset)
        name = " ".join(values["name"].split())
        if not name:
            raise DataLineageValidationError("Tên phép biến đổi không được để trống.")
        origin = values.get("origin", "manual")
        sql_text = values.get("sql_text")
        if sql_text is not None and len(sql_text.encode("utf-8")) > MAX_SQL_BYTES:
            raise DataLineageValidationError("SQL vượt quá 1 MB.")
        if origin in {"view_sql", "sql_job"} and not sql_text:
            raise DataLineageValidationError("Nguồn SQL cần câu lệnh định nghĩa phép biến đổi.")
        if origin == "view_sql" and not self._is_view(target):
            raise DataLineageValidationError("Nguồn view_sql chỉ dùng cho view hoặc materialized view.")
        dependencies = self._check_dependencies(
            target, set(source_ids), values.get("dependencies", []), visible,
        )
        fields = {
            "target_dataset_id": target_id, "name": name, "description": values.get("description"),
            "sql_text": sql_text, "origin": origin,
        }
        try:
            with self.session.begin_nested():
                row = self.transformations.read(transformation_id, lock=True) if transformation_id else None
                if transformation_id and (row is None or row.target_dataset_id != target_id):
                    raise LineageNotFoundError()
                if row is None:
                    row = self.transformations.create(LineageTransformation(**fields))
                else:
                    self.transformations.update(row, fields)
                self.transformations.replace_parts(row.id, source_ids, dependencies)
        except IntegrityError:
            raise LineageConflictError() from None
        return self.get_transformation(target.database_id, row.id, visible.values())

    def delete_transformation(self, transformation_id: UUID, datasets: Iterable[Any]) -> None:
        visible = {dataset.id: dataset for dataset in datasets if can_access_dataset(dataset)}
        row = self.transformations.read(transformation_id, lock=True)
        if row is None or row.target_dataset_id not in visible:
            raise LineageNotFoundError()
        require_edit(visible[row.target_dataset_id])
        self.transformations.delete(row)

    def preview(self, target_dataset_id: int, sql_text: str, datasets: Iterable[Any]) -> dict[str, Any]:
        visible = {dataset.id: dataset for dataset in datasets if can_access_dataset(dataset)}
        target = visible.get(target_dataset_id)
        if target is None:
            raise LineageNotFoundError("Không tìm thấy dataset đích trong database.")
        if not sql_text.strip() or len(sql_text.encode("utf-8")) > MAX_SQL_BYTES:
            raise DataLineageValidationError("SQL phải có nội dung và không vượt quá 1 MB.")
        return preview_sql(sql_text, target, visible)

    def read_view_sql(self, target_dataset_id: int, database_id: int) -> dict[str, Any]:
        dataset = require_dataset(target_dataset_id)
        require_dataset_access(dataset)
        if dataset.database_id != database_id:
            raise LineageNotFoundError("Dataset không thuộc database yêu cầu.")
        database = dataset.database
        try:
            with database.get_sqla_engine(schema=dataset.schema) as engine:
                inspector = inspect(engine)
                views = set(inspector.get_view_names(schema=dataset.schema))
                get_materialized_views = getattr(inspector, "get_materialized_view_names", None)
                if get_materialized_views is not None:
                    views.update(get_materialized_views(schema=dataset.schema))
                if dataset.table_name not in views:
                    raise DataLineageValidationError("Chỉ view và materialized view có SQL định nghĩa để đọc.")
                sql_text = inspector.get_view_definition(dataset.table_name, schema=dataset.schema)
        except DataLineageValidationError:
            raise
        except SQLAlchemyError:
            raise DataLineageValidationError("Không đọc được SQL định nghĩa view từ database.") from None
        if not sql_text:
            raise LineageNotFoundError("Không đọc được SQL định nghĩa view.")
        return {"target_dataset_id": target_dataset_id, "sql_text": sql_text}

    def _transformation_edges(self, datasets: dict[int, Any]) -> list[dict[str, Any]]:
        rows = self.transformations.list_for_datasets(datasets)
        inputs, dependencies = self.transformations.read_parts([row.id for row in rows])
        inputs_by_id: dict[UUID, list[int]] = {}
        dependencies_by_id: dict[UUID, list[dict[str, Any]]] = {}
        for item in inputs:
            inputs_by_id.setdefault(item.transformation_id, []).append(item.source_dataset_id)
        for item in dependencies:
            dependencies_by_id.setdefault(item.transformation_id, []).append({
                "source_dataset_id": item.source_dataset_id,
                "source_column_name": item.source_column_name,
                "target_column_name": item.target_column_name,
                "role": item.role,
            })
        return [
            {
                "source": source_id, "target": row.target_dataset_id, "kind": "transform",
                "origin": row.origin, "label": row.name, "color": None,
                "columns": [dependency for dependency in dependencies_by_id.get(row.id, [])
                            if dependency["source_dataset_id"] == source_id],
                "transformation_id": row.id,
            }
            for row in rows for source_id in inputs_by_id.get(row.id, [])
            if source_id in datasets and row.target_dataset_id in datasets
        ]

    def _check_dependencies(
        self, target: Any, source_ids: set[int], dependencies: list[dict[str, Any]], visible: dict[int, Any],
    ) -> list[dict[str, Any]]:
        target_columns = {str(column.column_name) for column in target.columns or []}
        source_columns = {
            dataset_id: {str(column.column_name) for column in dataset.columns or []}
            for dataset_id, dataset in visible.items() if dataset_id in source_ids
        }
        seen: set[tuple[int, str, str | None, str]] = set()
        checked: list[dict[str, Any]] = []
        for item in dependencies:
            source_id = item["source_dataset_id"]
            source_name = item["source_column_name"]
            target_name = item.get("target_column_name")
            role = item["role"]
            if role not in {"value", "group", "join", "filter"}:
                raise DataLineageValidationError("Vai trò cột không hợp lệ.")
            if source_id not in source_ids or source_name not in source_columns.get(source_id, set()):
                raise DataLineageValidationError("Cột nguồn phải thuộc dataset nguồn đang chọn.")
            if target_name is not None and target_name not in target_columns:
                raise DataLineageValidationError("Cột đích phải thuộc dataset đích.")
            if role == "value" and target_name is None:
                raise DataLineageValidationError("Liên kết value cần cột đích.")
            key = (source_id, source_name, target_name, role)
            if key in seen:
                raise DataLineageValidationError("Liên kết cột bị lặp.")
            seen.add(key)
            checked.append({
                "source_dataset_id": source_id, "source_column_name": source_name,
                "target_column_name": target_name, "role": role,
            })
        return checked

    @staticmethod
    def _is_view(dataset: Any) -> bool:
        try:
            with dataset.database.get_sqla_engine(schema=dataset.schema) as engine:
                inspector = inspect(engine)
                views = set(inspector.get_view_names(schema=dataset.schema))
                get_materialized_views = getattr(inspector, "get_materialized_view_names", None)
                if get_materialized_views is not None:
                    views.update(get_materialized_views(schema=dataset.schema))
                return dataset.table_name in views
        except SQLAlchemyError:
            return False

    @staticmethod
    def _transformation_out(
        row: LineageTransformation, source_ids: list[int], dependencies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": row.id, "target_dataset_id": row.target_dataset_id, "name": row.name,
            "description": row.description, "sql_text": row.sql_text, "origin": row.origin,
            "source_dataset_ids": source_ids, "dependencies": dependencies,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }
