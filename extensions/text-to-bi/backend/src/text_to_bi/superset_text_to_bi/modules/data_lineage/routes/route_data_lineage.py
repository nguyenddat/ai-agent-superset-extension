import json
import re
from typing import Any
from uuid import UUID

from flask import request
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset.extensions import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_text_to_bi.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION, OPENAPI_TAG
from text_to_bi.superset_text_to_bi.core.security import csrf_protected
from text_to_bi.superset_text_to_bi.core.validation import request_body
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import (
    require_admin,
    require_edit,
    require_view,
)
from text_to_bi.superset_text_to_bi.modules.data_dictionary.migrations import ensure_data_dictionary_tables
from text_to_bi.superset_text_to_bi.modules.management_payload import json_payload
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import (
    datasets_on_database,
    get_database,
    get_datasets,
)

from ..dependencies import data_lineage_service
from ..exceptions import DataLineageValidationError, LineageDatabaseNotFoundError
from ..migrations import ensure_data_lineage_tables
from ..schemas import PreviewIn, TransformationIn
from ..services.srv_data_lineage import EDGE_KINDS

_NODE_KEY = re.compile(r"^(table|metric)-\d+$")
_EDGE_KEY = re.compile(r"^((flow|relation|transform)-\d+-\d+|metric-edge-\d+)$")


def _database_id() -> int:
    database_id = request.args.get("database_id", type=int)
    if database_id is None or database_id < 1:
        raise DataLineageValidationError("database_id is required.")
    if get_database(database_id) is None:
        raise LineageDatabaseNotFoundError()
    return database_id


def _edge_key(payload: Any) -> tuple[int, int, str]:
    if not isinstance(payload, dict):
        raise DataLineageValidationError("Request body must be an object.")
    source, target, kind = payload.get("source"), payload.get("target"), payload.get("kind")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (source, target)):
        raise DataLineageValidationError("source and target must be positive Superset dataset IDs.")
    if source == target:
        raise DataLineageValidationError("An edge cannot connect a dataset to itself.")
    if kind not in EDGE_KINDS:
        raise DataLineageValidationError(f"kind must be one of: {', '.join(EDGE_KINDS)}.")
    return source, target, kind


def _editable_edge_datasets(source_id: int, target_id: int) -> list[Any]:
    datasets = get_datasets((source_id, target_id))
    if len(datasets) != 2:
        raise DataLineageValidationError("Unknown source or target dataset.")
    if datasets[0].database_id != datasets[1].database_id:
        raise DataLineageValidationError("Both datasets must belong to the same database.")
    for dataset in datasets:
        require_edit(dataset)
    return datasets


def _canvas_layout(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DataLineageValidationError("Request body must be an object.")
    nodes, edges = payload.get("nodes", {}), payload.get("edges", {})
    if not isinstance(nodes, dict) or not isinstance(edges, dict) or len(nodes) + len(edges) > 5000:
        raise DataLineageValidationError("nodes and edges must be objects containing at most 5000 items.")

    def point(value: Any) -> list[float]:
        if (not isinstance(value, list) or len(value) != 2 or
                any(isinstance(item, bool) or not isinstance(item, int | float) or abs(item) > 100_000
                    for item in value)):
            raise DataLineageValidationError("A point must be a pair of coordinates within the canvas.")
        return [round(float(value[0]), 1), round(float(value[1]), 1)]

    clean: dict[str, Any] = {"nodes": {}, "edges": {}}
    for key, position in nodes.items():
        if not _NODE_KEY.fullmatch(str(key)):
            raise DataLineageValidationError("Node keys must use table-<id> or metric-<id> format.")
        clean["nodes"][key] = point(position)
    for key, value in edges.items():
        if not _EDGE_KEY.fullmatch(str(key)) or not isinstance(value, dict):
            raise DataLineageValidationError("Invalid lineage edge layout key or value.")
        if value.get("style") not in ("orthogonal", "straight", "curved"):
            raise DataLineageValidationError("Edge style must be orthogonal, straight or curved.")
        waypoints = value.get("waypoints", [])
        if not isinstance(waypoints, list) or len(waypoints) > 50:
            raise DataLineageValidationError("An edge can have at most 50 waypoints.")
        coords = value.get("coords", [])
        if not isinstance(coords, list) or len(coords) > 100:
            raise DataLineageValidationError("An edge can have at most 100 coordinates.")
        if any(isinstance(item, bool) or not isinstance(item, int | float) or abs(item) > 100_000 for item in coords):
            raise DataLineageValidationError("Edge coordinates must be numbers within the canvas.")
        label = value.get("label")
        clean["edges"][key] = {
            "style": value["style"], "coords": [round(float(item), 1) for item in coords],
            "waypoints": [point(item) for item in waypoints],
            "label": None if label is None else point(label), "ports": point(value.get("ports", [0, 0])),
        }
    return clean


def _transformation_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise DataLineageValidationError("ID phép biến đổi không hợp lệ.") from error


@api(
    id="text_to_bi_data_lineage_api",
    name="Text to BI data lineage API",
    description="Manages dataset lineage transformations, inferred relationships and canvas layouts.",
    resource_name="data-lineage",
)
class DataLineageAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    # -------------------------READ---------------------------
    @expose("/graph", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_graph(self):
        require_view()
        ensure_data_dictionary_tables()
        ensure_data_lineage_tables()
        database_id = _database_id()
        return self.response(200, **data_lineage_service().graph(database_id, datasets_on_database(database_id)))

    @expose("/transformations", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_transformations(self):
        require_view()
        ensure_data_lineage_tables()
        database_id = _database_id()
        rows = data_lineage_service().list_transformations(database_id, datasets_on_database(database_id))
        return self.response(200, transformations=json_payload(rows))

    @expose("/transformations/<transformation_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_transformation(self, transformation_id: str):
        require_view()
        ensure_data_lineage_tables()
        database_id = _database_id()
        result = data_lineage_service().get_transformation(
            database_id, _transformation_id(transformation_id), datasets_on_database(database_id),
        )
        return self.response(200, transformation=json_payload(result))

    @expose("/transformations", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_transformation(self):
        body = request_body(TransformationIn)
        ensure_data_lineage_tables()
        database_id = _database_id()
        result = data_lineage_service().save_transformation(
            body.model_dump(), datasets_on_database(database_id),
        )
        db.session.commit()
        return self.response(201, transformation=json_payload(result))

    @expose("/transformations/<transformation_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_transformation(self, transformation_id: str):
        body = request_body(TransformationIn)
        ensure_data_lineage_tables()
        database_id = _database_id()
        result = data_lineage_service().save_transformation(
            body.model_dump(), datasets_on_database(database_id), _transformation_id(transformation_id),
        )
        db.session.commit()
        return self.response(200, transformation=json_payload(result))

    @expose("/transformations/<transformation_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_transformation(self, transformation_id: str):
        ensure_data_lineage_tables()
        database_id = _database_id()
        data_lineage_service().delete_transformation(
            _transformation_id(transformation_id), datasets_on_database(database_id),
        )
        db.session.commit()
        return self.response(200, message="Đã xóa phép biến đổi.")

    @expose("/preview", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def preview_transformation(self):
        require_view()
        body = request_body(PreviewIn)
        database_id = _database_id()
        result = data_lineage_service().preview(
            body.target_dataset_id, body.sql_text, datasets_on_database(database_id),
        )
        return self.response(200, **json_payload(result))

    @expose("/datasets/<int:dataset_id>/view-sql", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def read_view_sql(self, dataset_id: int):
        require_view()
        ensure_data_lineage_tables()
        database_id = _database_id()
        return self.response(
            200, **json_payload(data_lineage_service().read_view_sql(dataset_id, database_id)),
        )

    # -------------------------CREATE/UPDATE-----------------
    @expose("/canvas", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def save_canvas(self):
        require_admin()
        ensure_data_lineage_tables()
        database_id = _database_id()
        layout = _canvas_layout(request.get_json(silent=True))
        data_lineage_service().save_canvas(database_id, json.dumps(layout, separators=(",", ":")))
        db.session.commit()
        return self.response(200, database_id=database_id)

    @expose("/edges", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def add_edge(self):
        source_id, target_id, kind = _edge_key(request.get_json(silent=True))
        ensure_data_lineage_tables()
        _editable_edge_datasets(source_id, target_id)
        data_lineage_service().add_edge(source_id, target_id, kind)
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind)

    @expose("/edges/color", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def set_edge_color(self):
        payload = request.get_json(silent=True)
        source_id, target_id, kind = _edge_key(payload)
        color = payload.get("color")
        if color is not None and (not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{3,8}", color)):
            raise DataLineageValidationError("color must be a hex colour or null.")
        ensure_data_lineage_tables()
        _editable_edge_datasets(source_id, target_id)
        data_lineage_service().set_edge_color(source_id, target_id, kind, color)
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind, color=color)

    @expose("/edges", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def remove_edge(self):
        source_id, target_id, kind = _edge_key(request.get_json(silent=True))
        ensure_data_dictionary_tables()
        ensure_data_lineage_tables()
        datasets = _editable_edge_datasets(source_id, target_id)
        service = data_lineage_service()
        inferred = service.is_inferred(source_id, target_id, datasets) or (
            kind == "transform" and service.has_transformation(source_id, target_id)
        )
        service.remove_edge(source_id, target_id, kind, inferred)
        db.session.commit()
        return self.response(200, source=source_id, target=target_id, kind=kind)
