from superset.extensions import db

from .services import BusinessModelService


def business_model_service() -> BusinessModelService:
    return BusinessModelService(db.session)
