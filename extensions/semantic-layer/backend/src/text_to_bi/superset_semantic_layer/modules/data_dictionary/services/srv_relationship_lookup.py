from superset.connectors.sqla.models import SqlaTable

from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_dataset_draft import BASE_DATASET
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_dataset

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository
from ..models import ColumnDictionary
from .srv_relationship_contract import RelationshipEnd


def relationship_ends(fk_entry: ColumnDictionary) -> tuple[RelationshipEnd, RelationshipEnd] | None:
    """Hai đầu hiện tại của một khóa ngoại trong từ điển, kèm số cột khóa chính của mỗi bảng; None nếu mất một đầu."""
    if not fk_entry.referenced_column:
        return None
    column_repository = column_dictionary_repository()
    target_entry = column_repository.read(fk_entry.referenced_column)
    if target_entry is None:
        return None
    source = get_dataset(fk_entry.dataset_id)
    target = get_dataset(target_entry.dataset_id)
    if source is None or target is None:
        return None

    def end(dataset: SqlaTable, entry: ColumnDictionary) -> RelationshipEnd:
        live_names = {str(column.column_name) for column in dataset.columns}
        pk_count = sum(1 for row in column_repository.read_primary_keys(dataset.id) if row.column_name in live_names)
        return RelationshipEnd(dataset=dataset, entry=entry, pk_count=pk_count)

    return end(source, fk_entry), end(target, target_entry)


def base_tables(database_id: int) -> list[SqlaTable]:
    """Dataset vật lý loại base trên một database: các bảng schema link được join."""
    rows = dataset_dictionary_repository().read_datasets_of_type(database_id, BASE_DATASET)
    return [dataset for dataset, _dictionary in rows if not dataset.sql]
