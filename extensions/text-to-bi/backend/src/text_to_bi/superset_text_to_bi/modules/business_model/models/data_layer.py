from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_table_args


class DataLayer(AuditedModel):
    __tablename__ = "data_layers"
    __table_args__ = schema_table_args()

    name: Mapped[str] = Column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = Column(Text)
    color: Mapped[str | None] = Column(String(16))
    sort_order: Mapped[int] = Column(Integer, nullable=False, default=0, server_default="0")
    level: Mapped[int] = Column(Integer, nullable=False, default=0, server_default="0")
