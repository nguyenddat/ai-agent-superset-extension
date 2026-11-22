from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped

from text_to_bi.superset_text_to_bi.common.base_model import AuditedModel, BaseModel, schema_column, schema_table_args

business_domain_tables = Table(
    "business_domain_tables",
    BaseModel.metadata,
    Column(
        "domain_id", PostgresUUID(as_uuid=True),
        ForeignKey(schema_column("business_domains"), ondelete="CASCADE"), primary_key=True,
    ),
    Column(
        "table_dictionary_id", ForeignKey(schema_column("table_dictionaries"), ondelete="CASCADE"),
        primary_key=True, index=True,
    ),
    schema="text_to_bi",
)
class BusinessDomain(AuditedModel):
    __tablename__ = "business_domains"
    __table_args__ = schema_table_args()
    name: Mapped[str] = Column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = Column(Text)
    color: Mapped[str | None] = Column(String(16))
