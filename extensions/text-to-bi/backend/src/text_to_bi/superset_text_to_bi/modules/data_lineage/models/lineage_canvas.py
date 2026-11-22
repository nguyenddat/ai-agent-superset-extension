from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_table_args
from text_to_bi.superset_text_to_bi.modules.data_dictionary.models import SupersetDatabase


class LineageCanvas(AuditedModel):
    __tablename__ = "lineage_canvases"
    __table_args__ = schema_table_args(UniqueConstraint("database_id", name="uq_lineage_canvases_database_id"))

    database_id: Mapped[int] = Column(
        Integer, ForeignKey(SupersetDatabase.id, ondelete="CASCADE"), nullable=False, index=True
    )
    layout: Mapped[str] = Column(Text, nullable=False)
