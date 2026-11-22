from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_model import TEXT_TO_BI_SCHEMA, BaseModel


class DomainAssignment:
    def __init__(self, session: Session, association: Any, owner_column: str) -> None:
        self.session = session
        self.association = association
        self.owner = association.c[owner_column]

    def _domains(self) -> Any:
        return BaseModel.metadata.tables.get(f"{TEXT_TO_BI_SCHEMA}.business_domains")

    def unknown(self, domain_ids: Iterable[UUID]) -> list[UUID]:
        wanted = list(dict.fromkeys(domain_ids))
        if not wanted:
            return []
        domains = self._domains()
        if domains is None:
            return wanted
        found = set(self.session.scalars(select(domains.c.id).where(domains.c.id.in_(wanted))))
        return [domain_id for domain_id in wanted if domain_id not in found]

    def ids(self, owner_id: UUID) -> set[UUID]:
        if self._domains() is None:
            return set()
        return set(self.session.scalars(select(self.association.c.domain_id).where(self.owner == owner_id)))

    def read_one(self, owner_id: UUID) -> list[dict[str, Any]]:
        domains = self._domains()
        if domains is None:
            return []
        rows = self.session.execute(
            select(domains.c.id, domains.c.name, domains.c.color)
            .join(self.association, self.association.c.domain_id == domains.c.id)
            .where(self.owner == owner_id).order_by(domains.c.name)
        )
        return [{"id": domain_id, "name": name, "color": color} for domain_id, name, color in rows]

    def replace(self, owner_id: UUID, domain_ids: Iterable[UUID]) -> None:
        if self._domains() is None:
            return
        self.session.execute(delete(self.association).where(self.owner == owner_id))
        wanted = list(dict.fromkeys(domain_ids))
        if wanted:
            self.session.execute(insert(self.association), [
                {self.owner.name: owner_id, "domain_id": domain_id} for domain_id in wanted
            ])
