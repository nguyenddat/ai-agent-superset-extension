import re

from flask_appbuilder import Model
from sqlalchemy.orm import declared_attr

TABLE_PREFIX = "text_to_bi_"


class BaseModel(Model):
    __abstract__ = True

    @declared_attr
    def __tablename__(cls) -> str:
        return TABLE_PREFIX + re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
