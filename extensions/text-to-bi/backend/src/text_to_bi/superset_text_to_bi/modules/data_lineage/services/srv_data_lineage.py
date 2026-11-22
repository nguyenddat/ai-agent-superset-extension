import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.modules.data_dictionary.repositories import ColumnDictionaryRepository
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import can_access_dataset

from ..models import LineageCanvas, LineageEdge
from ..repositories import LineageCanvasRepository, LineageEdgeRepository

EDGE_KINDS = ("flow", "relation", "transform")


class DataLineageService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.edges = LineageEdgeRepository(session)
        self.canvases = LineageCanvasRepository(session)
        self.columns = ColumnDictionaryRepository(session)

    # -------------------------READ---------------------------
    def graph(self, database_id: int, datasets: Iterable[Any]) -> dict[str, Any]:
        visible = {dataset.id: dataset for dataset in datasets if can_access_dataset(dataset)}
        references = self.columns.read_references(visible)
        inferred: dict[tuple[int, int, str], dict[str, Any]] = {}
        for source_id, source_column, target_id, target_column in references:
            if source_id not in visible or target_id not in visible or source_id == target_id:
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
        for key, row in by_key.items():
            if row.is_manual and not row.is_hidden and key not in inferred:
                inferred[key] = {
                    "source": row.source_dataset_id, "target": row.target_dataset_id, "kind": row.kind,
                    "origin": "manual", "label": row.label, "color": row.color, "columns": [],
                }
        canvas = self.canvases.read_for_database(database_id)
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
        rows = self.columns.read_references({dataset.id for dataset in datasets})
        return any(
            source_id == source and target_id == target and source != target
            for source, _source_column, target, _target_column in rows
        )

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
