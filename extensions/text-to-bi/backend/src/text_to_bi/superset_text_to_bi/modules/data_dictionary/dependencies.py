from superset.extensions import db

from .services import DataDictionaryAutofillService, DataDictionaryService, SupersetCatalogService


def data_dictionary_service() -> DataDictionaryService:
    return DataDictionaryService(db.session)


def data_dictionary_autofill_service() -> DataDictionaryAutofillService:
    return DataDictionaryAutofillService(db.session)


def superset_catalog_service() -> SupersetCatalogService:
    return SupersetCatalogService(db.session)
