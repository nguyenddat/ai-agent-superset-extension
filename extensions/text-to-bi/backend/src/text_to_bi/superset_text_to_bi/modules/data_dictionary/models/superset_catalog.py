"""Aliases to the Superset metadata models used by the data dictionary."""

from superset.connectors.sqla.models import SqlaTable as SupersetDataset
from superset.connectors.sqla.models import TableColumn as SupersetDatasetColumn
from superset.models.core import Database as SupersetDatabase

__all__ = ["SupersetDatabase", "SupersetDataset", "SupersetDatasetColumn"]
