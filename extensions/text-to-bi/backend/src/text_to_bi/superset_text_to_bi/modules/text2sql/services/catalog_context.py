from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import (
    ColumnDictionary,
    ColumnSynonym,
    SupersetDataset,
    SupersetDatasetColumn,
    TableDictionary,
)
from text_to_bi.superset_text_to_bi.modules.metric_management.models import Metric
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import readable_datasets


@dataclass(frozen=True)
class TableEntry:
    table: SupersetDataset
    dictionary: TableDictionary | None

    @property
    def label(self) -> str:
        return self.dictionary.display_name if self.dictionary else self.table.table_name

    @property
    def qualified_name(self) -> str:
        schema = self.table.schema
        return f"{schema}.{self.table.table_name}" if schema else self.table.table_name


@dataclass(frozen=True)
class ColumnEntry:
    column: SupersetDatasetColumn
    dictionary: ColumnDictionary | None
    synonyms: list[str]

    @property
    def label(self) -> str:
        return self.dictionary.display_name if self.dictionary else self.column.column_name


@dataclass
class CatalogContext:
    database_id: int
    tables: dict[int, TableEntry]
    columns: list[ColumnEntry]
    metrics: list[Metric]
    columns_by_id: dict[int, ColumnEntry] = field(default_factory=dict)
    columns_by_table: dict[int, dict[str, int]] = field(default_factory=dict)
    metrics_by_id: dict[object, Metric] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for entry in self.columns:
            self.columns_by_id[entry.column.id] = entry
            self.columns_by_table.setdefault(entry.column.table_id, {})[
                entry.column.column_name.lower()
            ] = entry.column.id
        self.metrics_by_id = {metric.id: metric for metric in self.metrics}

    def table_label(self, table_id: int | None) -> str | None:
        entry = self.tables.get(table_id) if table_id is not None else None
        return entry.label if entry else None

    def column_label(self, column_id: int) -> str | None:
        entry = self.columns_by_id.get(column_id)
        return entry.label if entry else None

    def metric_label(self, metric_id: object) -> str | None:
        metric = self.metrics_by_id.get(metric_id)
        return (metric.label or metric.name) if metric else None


def load_context(session: Session, database_id: int) -> CatalogContext:
    accessible_ids = {
        dataset.id for dataset in readable_datasets() if dataset.database_id == database_id
    }
    table_rows = session.execute(
        select(SupersetDataset, TableDictionary)
        .outerjoin(TableDictionary, TableDictionary.dataset_id == SupersetDataset.id)
        .where(SupersetDataset.id.in_(accessible_ids))
        .order_by(SupersetDataset.schema, SupersetDataset.table_name, SupersetDataset.id)
    ).all()
    tables = {table.id: TableEntry(table, dictionary) for table, dictionary in table_rows}
    table_ids = list(tables)

    column_rows = session.execute(
        select(SupersetDatasetColumn, ColumnDictionary)
        .outerjoin(
            ColumnDictionary,
            (ColumnDictionary.dataset_id == SupersetDatasetColumn.table_id)
            & (ColumnDictionary.column_name == SupersetDatasetColumn.column_name),
        )
        .where(SupersetDatasetColumn.table_id.in_(table_ids))
        .order_by(SupersetDatasetColumn.table_id, SupersetDatasetColumn.id)
    ).all() if table_ids else []

    dictionary_ids = [dictionary.id for _, dictionary in column_rows if dictionary is not None]
    synonyms: dict[object, list[str]] = {}
    if dictionary_ids:
        synonym_rows = session.scalars(
            select(ColumnSynonym).where(ColumnSynonym.column_dictionary_id.in_(dictionary_ids))
        )
        for row in synonym_rows:
            synonyms.setdefault(row.column_dictionary_id, []).append(row.synonym)

    columns = [
        ColumnEntry(column, dictionary, synonyms.get(dictionary.id, []) if dictionary else [])
        for column, dictionary in column_rows
    ]
    metrics = list(session.scalars(
        select(Metric).where(
            Metric.dataset_id.in_(table_ids), Metric.is_active.is_(True), Metric.status == "approved",
        )
    ).all()) if table_ids else []
    return CatalogContext(database_id=database_id, tables=tables, columns=columns, metrics=metrics)
