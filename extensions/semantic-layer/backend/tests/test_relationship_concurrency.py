from sqlalchemy import Column, Integer, Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from text_to_bi.superset_semantic_layer.modules.data_dictionary.models import RelationshipContract


def test_two_transactions_cannot_overwrite_a_relationship_review():
    metadata = RelationshipContract.metadata
    Table("tables", metadata, Column("id", Integer, primary_key=True), extend_existing=True)
    Table("ab_user", metadata, Column("id", Integer, primary_key=True), extend_existing=True)
    engine = create_engine("sqlite://")
    metadata.tables["tables"].create(engine)
    metadata.tables["ab_user"].create(engine)
    RelationshipContract.__table__.create(engine)
    with Session(engine) as seed:
        seed.add(
            RelationshipContract(
                from_dataset_id=1, from_column="city_id", to_dataset_id=2, to_column="id",
                cardinality="many_to_one", contract_hash="a" * 64, status="candidate",
            )
        )
        seed.commit()

    first = Session(engine)
    second = Session(engine)
    first_contract = first.query(RelationshipContract).one()
    second_contract = second.query(RelationshipContract).one()
    first_contract.status = "approved"
    first.commit()
    second_contract.status = "revoked"
    try:
        second.commit()
    except StaleDataError:
        second.rollback()
    else:
        raise AssertionError("A stale relationship transaction overwrote the committed review.")
    with Session(engine) as reader:
        assert reader.query(RelationshipContract.status).scalar() == "approved"
    first.close()
    second.close()
