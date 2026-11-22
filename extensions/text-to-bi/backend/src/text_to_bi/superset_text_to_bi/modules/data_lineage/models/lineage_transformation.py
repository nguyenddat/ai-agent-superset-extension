from uuid import UUID

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, BaseModel, schema_table_args
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetDataset


class LineageTransformation(AuditedModel):
    __tablename__ = "lineage_transformations"
    __table_args__ = schema_table_args(
        UniqueConstraint("target_dataset_id", "name", name="uq_lineage_transformation_name"),
        CheckConstraint("origin IN ('manual', 'sql_job', 'view_sql')", name="origin_valid"),
    )

    target_dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = Column(String(255), nullable=False)
    description: Mapped[str | None] = Column(Text)
    sql_text: Mapped[str | None] = Column(Text)
    origin: Mapped[str] = Column(String(24), nullable=False, default="manual", server_default="manual")


class LineageTransformationInput(BaseModel):
    __tablename__ = "lineage_transformation_inputs"
    __table_args__ = schema_table_args(
        UniqueConstraint("transformation_id", "source_dataset_id", name="uq_lineage_transformation_input"),
    )

    transformation_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(LineageTransformation.id, ondelete="CASCADE"), nullable=False,
        index=True,
    )
    source_dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True,
    )


class LineageColumnDependency(BaseModel):
    __tablename__ = "lineage_column_dependencies"
    __table_args__ = schema_table_args(
        CheckConstraint("role IN ('value', 'group', 'join', 'filter')", name="role_valid"),
        CheckConstraint("role <> 'value' OR target_column_name IS NOT NULL", name="value_has_target"),
    )

    transformation_id: Mapped[UUID] = Column(
        PostgresUUID(as_uuid=True), ForeignKey(LineageTransformation.id, ondelete="CASCADE"), nullable=False,
        index=True,
    )
    source_dataset_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDataset.id, ondelete="CASCADE"), nullable=False, index=True,
    )
    source_column_name: Mapped[str] = Column(String(255), nullable=False)
    target_column_name: Mapped[str | None] = Column(String(255))
    role: Mapped[str] = Column(String(16), nullable=False)
