from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, schema_table_args


class DataLayer(AuditedModel):
    __tablename__ = "data_layers"
    __table_args__ = schema_table_args()

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
