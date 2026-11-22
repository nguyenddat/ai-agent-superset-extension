from collections.abc import Collection
from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import TableDictionary

from ..models import BusinessCanvas, BusinessDomain, DataLayer, DatasetLayer, business_domain_tables


class DataLayerRepository(BaseRepository[DataLayer]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DataLayer)
    def ordered(self) -> list[DataLayer]:
        statement = select(self.model).order_by(self.model.level, self.model.sort_order, self.model.name)
        return list(self.session.scalars(statement).all())
    def by_name(self, name: str) -> DataLayer | None:
        return self.session.scalar(select(self.model).where(func.lower(self.model.name) == name.lower()))

class BusinessDomainRepository(BaseRepository[BusinessDomain]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, BusinessDomain)
    def ordered(self) -> list[BusinessDomain]:
        return list(self.session.scalars(select(self.model).order_by(self.model.name)).all())
    def by_name(self, name: str) -> BusinessDomain | None:
        return self.session.scalar(select(self.model).where(func.lower(self.model.name) == name.lower()))
    def memberships(self, dataset_ids: Collection[int] | None = None) -> dict[object, list[int]]:
        statement = select(business_domain_tables.c.domain_id, TableDictionary.dataset_id).join(
            TableDictionary, business_domain_tables.c.table_dictionary_id == TableDictionary.id
        )
        if dataset_ids is not None:
            statement = statement.where(TableDictionary.dataset_id.in_(dataset_ids))
        result: dict[object, list[int]] = {}
        for domain_id, dataset_id in self.session.execute(statement):
            result.setdefault(domain_id, []).append(dataset_id)
        return result
    def replace_memberships(self, domain_id: UUID, dictionary_ids: Collection[UUID]) -> None:
        self.session.execute(delete(business_domain_tables).where(business_domain_tables.c.domain_id == domain_id))
        if dictionary_ids:
            self.session.execute(
                insert(business_domain_tables),
                [
                    {"domain_id": domain_id, "table_dictionary_id": dictionary_id}
                    for dictionary_id in dictionary_ids
                ],
            )

class BusinessCanvasRepository(BaseRepository[BusinessCanvas]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, BusinessCanvas)
    def by_database(self, database_id: int) -> BusinessCanvas | None:
        return self.session.scalar(select(self.model).where(self.model.database_id == database_id))

class DatasetLayerRepository(BaseRepository[DatasetLayer]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DatasetLayer)
    def by_dataset(self, dataset_id: int) -> DatasetLayer | None:
        return self.session.scalar(select(self.model).where(self.model.dataset_id == dataset_id))
    def by_datasets(self, dataset_ids: Collection[int]) -> dict[int, DatasetLayer]:
        if not dataset_ids:
            return {}
        rows = self.session.scalars(select(self.model).where(self.model.dataset_id.in_(dataset_ids))).all()
        return {row.dataset_id: row for row in rows}
