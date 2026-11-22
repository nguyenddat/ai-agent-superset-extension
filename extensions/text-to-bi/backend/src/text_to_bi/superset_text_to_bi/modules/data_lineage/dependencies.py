from superset.extensions import db

from .repositories import LineageCanvasRepository, LineageEdgeRepository, LineageTransformationRepository
from .services import DataLineageService


def data_lineage_service() -> DataLineageService:
    return DataLineageService(db.session)


def lineage_edge_repository() -> LineageEdgeRepository:
    return LineageEdgeRepository(db.session)


def lineage_canvas_repository() -> LineageCanvasRepository:
    return LineageCanvasRepository(db.session)


def lineage_transformation_repository() -> LineageTransformationRepository:
    return LineageTransformationRepository(db.session)
