from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import ChildRepository

from ..models import ColumnAggregation, ColumnSynonym, IndicatorAggregation, TableColumnRole, TableTimeGrain


class TableColumnRoleRepository(ChildRepository[TableColumnRole]):
    parent_key = "table_dictionary_id"

    def __init__(self, session: Session) -> None:
        super().__init__(session, TableColumnRole)


class TableTimeGrainRepository(ChildRepository[TableTimeGrain]):
    parent_key = "table_dictionary_id"

    def __init__(self, session: Session) -> None:
        super().__init__(session, TableTimeGrain)


class IndicatorAggregationRepository(ChildRepository[IndicatorAggregation]):
    parent_key = "table_dictionary_id"

    def __init__(self, session: Session) -> None:
        super().__init__(session, IndicatorAggregation)


class ColumnAggregationRepository(ChildRepository[ColumnAggregation]):
    parent_key = "column_dictionary_id"

    def __init__(self, session: Session) -> None:
        super().__init__(session, ColumnAggregation)


class ColumnSynonymRepository(ChildRepository[ColumnSynonym]):
    parent_key = "column_dictionary_id"

    def __init__(self, session: Session) -> None:
        super().__init__(session, ColumnSynonym)
