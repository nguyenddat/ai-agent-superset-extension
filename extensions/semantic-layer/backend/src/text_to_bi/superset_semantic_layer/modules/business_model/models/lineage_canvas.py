from sqlalchemy import Column, ForeignKey, Integer, Text

from ....common.base_model import AuditedModel


class LineageCanvas(AuditedModel):
    __table_args__ = ({"extend_existing": True},)

    database_id = Column(Integer, ForeignKey("dbs.id", ondelete="CASCADE"), primary_key=True)
    layout = Column(Text, nullable=False)
