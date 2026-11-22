# pyright: reportAssignmentType=false

from datetime import datetime
from typing import Any
from uuid import UUID

from flask_appbuilder import Model
from sqlalchemy import Column, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, declared_attr

from .utils.identifiers import uuid7
from .utils.request_user import request_user_id
from .utils.type_formatters import utc_now

# Every table of the extension lives in this PostgreSQL schema of Superset's metadata database, apart from Superset's
# own tables and from the tables of the two older extensions.
TEXT_TO_BI_SCHEMA = "text_to_bi"


def schema_table_args(*constraints: Any) -> tuple[Any, ...]:
    return (*constraints, {"schema": TEXT_TO_BI_SCHEMA})


def schema_column(table_name: str, column_name: str = "id") -> str:
    return f"{TEXT_TO_BI_SCHEMA}.{table_name}.{column_name}"


class BaseModel(Model):
    __abstract__ = True
    __table_args__ = schema_table_args()

    id: Mapped[UUID] = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now()
    )


# Who created and last changed a row, as Superset's own models record it: the ab_user.id of the signed-in user.
class AuditedModel(BaseModel):
    __abstract__ = True

    @declared_attr
    def created_by_fk(cls) -> Mapped[int | None]:
        return Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, default=request_user_id)

    @declared_attr
    def changed_by_fk(cls) -> Mapped[int | None]:
        return Column(
            Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True, default=request_user_id,
            onupdate=request_user_id,
        )
