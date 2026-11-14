from superset import db

from .repositories.repo_column_dictionary import ColumnDictionaryRepository
from .repositories.repo_column_transformation import ColumnTransformationRepository
from .repositories.repo_dataset_dictionary import DatasetDictionaryRepository
from .repositories.repo_dataset_grain import DatasetGrainRepository
from .repositories.repo_relationship_contract import RelationshipContractRepository


def column_dictionary_repository() -> ColumnDictionaryRepository:
    return ColumnDictionaryRepository(db.session)


def column_transformation_repository() -> ColumnTransformationRepository:
    return ColumnTransformationRepository(db.session)


def dataset_dictionary_repository() -> DatasetDictionaryRepository:
    return DatasetDictionaryRepository(db.session)


def dataset_grain_repository() -> DatasetGrainRepository:
    return DatasetGrainRepository(db.session)


def relationship_contract_repository() -> RelationshipContractRepository:
    return RelationshipContractRepository(db.session)
