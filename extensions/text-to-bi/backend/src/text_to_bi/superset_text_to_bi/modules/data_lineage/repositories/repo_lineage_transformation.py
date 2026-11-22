from collections.abc import Collection
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.base_repository import BaseRepository

from ..models import LineageColumnDependency, LineageTransformation, LineageTransformationInput


class LineageTransformationRepository(BaseRepository[LineageTransformation]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, LineageTransformation)

    def list_for_datasets(self, dataset_ids: Collection[int]) -> list[LineageTransformation]:
        if not dataset_ids:
            return []
        statement = select(self.model).where(self.model.target_dataset_id.in_(dataset_ids))
        return list(self.session.scalars(statement.order_by(self.model.name, self.model.id)).all())

    def read(self, transformation_id: UUID, lock: bool = False) -> LineageTransformation | None:
        statement = select(self.model).where(self.model.id == transformation_id)
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def has_edge(self, source_dataset_id: int, target_dataset_id: int) -> bool:
        statement = (
            select(LineageTransformationInput.id)
            .join(LineageTransformation, LineageTransformation.id == LineageTransformationInput.transformation_id)
            .where(
                LineageTransformationInput.source_dataset_id == source_dataset_id,
                LineageTransformation.target_dataset_id == target_dataset_id,
            )
            .limit(1)
        )
        return self.session.scalar(statement) is not None

    def read_parts(
        self, transformation_ids: Collection[UUID],
    ) -> tuple[list[LineageTransformationInput], list[LineageColumnDependency]]:
        if not transformation_ids:
            return [], []
        inputs = self.session.scalars(
            select(LineageTransformationInput)
            .where(LineageTransformationInput.transformation_id.in_(transformation_ids))
            .order_by(LineageTransformationInput.id)
        ).all()
        dependencies = self.session.scalars(
            select(LineageColumnDependency)
            .where(LineageColumnDependency.transformation_id.in_(transformation_ids))
            .order_by(LineageColumnDependency.id)
        ).all()
        return list(inputs), list(dependencies)

    def replace_parts(
        self, transformation_id: UUID, source_dataset_ids: list[int], dependencies: list[dict],
    ) -> None:
        self.session.execute(delete(LineageColumnDependency).where(
            LineageColumnDependency.transformation_id == transformation_id
        ))
        self.session.execute(delete(LineageTransformationInput).where(
            LineageTransformationInput.transformation_id == transformation_id
        ))
        self.session.add_all([
            LineageTransformationInput(transformation_id=transformation_id, source_dataset_id=dataset_id)
            for dataset_id in source_dataset_ids
        ])
        self.session.add_all([
            LineageColumnDependency(transformation_id=transformation_id, **item) for item in dependencies
        ])
        self.session.flush()
