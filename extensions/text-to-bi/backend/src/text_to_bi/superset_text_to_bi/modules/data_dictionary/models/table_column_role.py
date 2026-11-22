# pyright: reportAssignmentType=false

from uuid import UUID

from sqlalchemy import Column, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_column, schema_table_args


class TableColumnRole(AuditedModel):
    __tablename__ = "table_column_roles"

    table_dictionary_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(schema_column("table_dictionaries"), ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = Column(String(32), nullable=False)
    qualifier: Mapped[str | None] = Column(String(32))
    # Columns are named, not referenced: Superset may delete and recreate `table_columns` rows when a dataset is
    # synced, while the name stays.
    column_name: Mapped[str] = Column(String(255), nullable=False)

    # One column per (role, qualifier); COALESCE stands in for NULLS NOT DISTINCT, which SQLAlchemy 1.4 cannot declare.
    __table_args__ = schema_table_args(
        Index(
            "uq_table_column_roles_role", table_dictionary_id, role, func.coalesce(qualifier, ""), unique=True
        ),
    )
