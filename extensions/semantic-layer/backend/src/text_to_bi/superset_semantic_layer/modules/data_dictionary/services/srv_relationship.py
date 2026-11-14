import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from superset.connectors.sqla.models import SqlaTable

from text_to_bi.superset_semantic_layer.core.security import second_reviewer_required
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_dataset_draft import BASE_DATASET
from text_to_bi.superset_semantic_layer.modules.superset.services.srv_dataset import get_dataset

from ..dependencies import column_dictionary_repository, dataset_dictionary_repository, relationship_contract_repository
from ..exceptions import (
    ApprovedContractExistsError,
    ForeignKeyColumnNotFoundError,
    RelationshipCandidateRequiredError,
    RelationshipContractNotFoundError,
    RelationshipSelfApprovalError,
    RelationshipValidationError,
)
from ..models import ColumnDictionary, RelationshipContract
from ..utils.util_serializer import serialize_relationship_contract
from .srv_relationship_contract import RelationshipEnd, relationship_cardinality, relationship_contract_hash, relationship_is_approved_current
from .srv_relationship_discovery import (
    SOURCES,
    VERIFICATION_TIMEOUT_MS,
    TableKeys,
    current_verification,
    database_suggestions,
    merged_suggestions,
    naming_suggestions,
    types_match,
    verification_queries,
    verification_result,
)
from .srv_relationship_lookup import base_tables, relationship_ends
from .srv_seeding import seed_dictionary

logger = logging.getLogger(__name__)


class RelationshipService:
    def __init__(self) -> None:
        self.columns = column_dictionary_repository()
        self.contracts = relationship_contract_repository()

    # -------------------------CREATE-------------------------
    def create_candidate(self, dataset_id: int, column_id: int, origin: Any, actor_id: int) -> tuple[RelationshipContract, RelationshipEnd, RelationshipEnd]:
        """Chụp một khóa ngoại đủ điều kiện thành contract đề xuất chờ quản trị viên duyệt."""
        source, target = self._context(dataset_id, column_id)
        contract = self._snapshot_candidate(source, target, origin if origin in SOURCES else None, actor_id)
        if contract is None:
            raise ApprovedContractExistsError()
        return contract, source, target

    def apply_suggestion(self, dataset: SqlaTable, payload: Any, actor_id: int) -> dict[str, Any]:
        """Khai báo một quan hệ được gợi ý vào Data Dictionary và chụp nó thành contract đề xuất.

        Khóa ngoại của database chỉ trỏ được vào khóa, nên đích được đánh dấu unique khi từ điển chưa nói vậy; gợi ý
        theo tên cột cần đích đã được khai báo là khóa.
        """
        if not isinstance(payload, dict) or payload.get("source") not in SOURCES:
            raise RelationshipValidationError("The body needs from_column, to_dataset_id, to_column and a source.")
        target_dataset = get_dataset(payload.get("to_dataset_id")) if isinstance(payload.get("to_dataset_id"), int) and not isinstance(payload.get("to_dataset_id"), bool) else None
        base_ids = {item.id for item in base_tables(dataset.database_id)}
        if dataset.id not in base_ids or target_dataset is None or target_dataset.id not in base_ids:
            raise RelationshipValidationError("Both ends must be base tables on the same database.")
        seed_dictionary(dataset)
        seed_dictionary(target_dataset)
        source_entry = self.columns.read_by_column_name(dataset.id, payload.get("from_column"))
        target_entry = self.columns.read_by_column_name(target_dataset.id, payload.get("to_column"))
        if source_entry is None or target_entry is None:
            raise RelationshipValidationError("Unknown source or target column.")
        contract_reader = getattr(self.contracts, "read_for_update", self.contracts.read_by_from_column)
        current_contract = contract_reader(dataset.id, source_entry.column_name)
        if current_contract is not None and current_contract.status == "approved":
            raise ApprovedContractExistsError()
        if target_entry.column_name not in self._table_keys(target_dataset).unique_columns:
            if payload["source"] != "database":
                raise RelationshipValidationError("Declare the target column a key or unique before using it.")
            target_entry.is_unique = True
        source_entry.is_fk = True
        source_entry.referenced_column = target_entry.id
        self.columns.flush()
        ends = relationship_ends(source_entry)
        contract = self._snapshot_candidate(*ends, payload["source"], actor_id) if ends else None
        if contract is None:
            raise ApprovedContractExistsError("Revoke the current approved contract before declaring another target.")
        return self.read_row(source_entry)

    # -------------------------READ---------------------------
    def read_all(self, dataset: SqlaTable, suggest: bool) -> dict[str, Any]:
        """Quan hệ đã khai báo của dataset, đi ra và đi vào, kèm contract và kết quả kiểm tra dữ liệu.

        Với `suggest`, thêm các quan hệ mà database, từ điển và tên cột gợi ý từ một dataset base sang dataset base
        khác cùng database và chưa được khai báo.
        """
        entries = self.columns.read_by_dataset(dataset.id)
        outgoing = [row for row in (self.read_row(entry) for entry in entries if entry.is_fk) if row]
        incoming_entries = self.columns.read_referencing([entry.id for entry in entries]) if entries else []
        incoming = [row for row in (self.read_row(entry) for entry in incoming_entries) if row]
        dictionary = dataset_dictionary_repository().read(dataset.id)
        is_base = getattr(dictionary, "dataset_type", None) == BASE_DATASET and not dataset.sql
        payload = {"dataset_id": dataset.id, "is_base": is_base, "outgoing": outgoing, "incoming": incoming}
        if suggest and is_base:
            payload.update(self._read_suggestions(dataset, outgoing))
        return payload

    def read_row(self, entry: ColumnDictionary) -> dict[str, Any] | None:
        """Một quan hệ khai báo trên cột khóa ngoại: hai đầu, lực lượng hoặc lý do không hợp lệ, và contract."""
        ends = relationship_ends(entry)
        if ends is None:
            return None
        source, target = ends
        try:
            cardinality, problem = relationship_cardinality(source, target), None
        except ValueError as ex:
            cardinality, problem = None, str(ex)
        contract = self.contracts.read_by_from_column(source.dataset.id, entry.column_name)
        return {
            "column_id": entry.id,
            "from_dataset_id": source.dataset.id,
            "from_dataset_name": source.dataset.table_name,
            "from_column": entry.column_name,
            "to_dataset_id": target.dataset.id,
            "to_dataset_name": target.dataset.table_name,
            "to_column": target.entry.column_name,
            "cardinality": cardinality,
            "problem": problem,
            "contract": serialize_relationship_contract(contract, source, target) if contract else None,
        }

    # -------------------------UPDATE-------------------------
    def approve(self, dataset_id: int, column_id: int, actor_id: int) -> tuple[RelationshipContract, RelationshipEnd, RelationshipEnd]:
        """Duyệt contract đề xuất còn khớp quan hệ hiện tại và đã qua kiểm tra dữ liệu."""
        source, target = self._context(dataset_id, column_id)
        contract_reader = getattr(self.contracts, "read_for_update", self.contracts.read_by_from_column)
        contract = contract_reader(source.dataset.id, source.entry.column_name)
        if contract is None:
            raise RelationshipContractNotFoundError()
        if contract.status != "candidate":
            raise RelationshipValidationError("Only a candidate relationship contract can be approved.")
        cardinality = relationship_cardinality(source, target)
        if contract.contract_hash != relationship_contract_hash(source, target, cardinality):
            raise RelationshipValidationError("Relationship changed; create a new candidate before approval.")
        verification = current_verification(contract)
        if not verification or not verification.get("passed"):
            raise RelationshipValidationError("Check the data first: the target column must hold each value once and the types must match.")
        if second_reviewer_required() and contract.owner_id == actor_id:
            raise RelationshipSelfApprovalError()
        contract.status = "approved"
        contract.approver_id = actor_id
        contract.approved_at = datetime.now(timezone.utc)
        return contract, source, target

    def revoke(self, dataset_id: int, column_id: int, contract_id: int | None, actor_id: int) -> tuple[RelationshipContract, ColumnDictionary | None]:
        """Thu hồi contract của khóa ngoại; trả contract và cột khóa ngoại trên URL (None nếu không còn)."""
        entry = self.columns.read_in_dataset(dataset_id, column_id)
        contract_reader = getattr(self.contracts, "read_for_update", self.contracts.read_by_from_column)
        contract = contract_reader(dataset_id, entry.column_name) if entry is not None else None
        if contract_id is not None:
            candidate = self.contracts.read(contract_id)
            # A contract ID is only an alternate key for this route's relationship when
            # the path FK entry independently binds it to the same source column. If the
            # entry is gone, the request no longer carries enough information to prove
            # which relationship the caller intended, even when the ID belongs to this dataset.
            if (
                candidate is None
                or entry is None
                or candidate.from_dataset_id != dataset_id
                or candidate.from_column != entry.column_name
                or (contract is not None and candidate.id != contract.id)
            ):
                raise RelationshipContractNotFoundError()
            contract = candidate
        if contract is None:
            raise RelationshipContractNotFoundError()
        if contract.status != "approved":
            raise RelationshipValidationError("Chỉ được thu hồi quan hệ đang được duyệt.")
        contract.status = "revoked"
        contract.revoker_id = actor_id
        contract.revoked_at = datetime.now(timezone.utc)
        return contract, entry

    def verify(self, dataset_id: int, column_id: int) -> tuple[RelationshipContract, RelationshipEnd, RelationshipEnd] | None:
        """Kiểm tra dữ liệu có đúng quan hệ không và lưu kết quả lên contract; None khi không chạy được truy vấn.

        Truy vấn join hai bảng, việc ChartData của một dataset không làm được, nên chạy chỉ đọc trên engine của
        database với statement timeout; chỉ quản trị viên tới được đây.
        """
        source, target = self._context(dataset_id, column_id)
        contract_reader = getattr(self.contracts, "read_for_update", self.contracts.read_by_from_column)
        contract = contract_reader(source.dataset.id, source.entry.column_name)
        if contract is None or contract.status == "revoked":
            raise RelationshipCandidateRequiredError()
        cardinality = relationship_cardinality(source, target)
        if contract.contract_hash != relationship_contract_hash(source, target, cardinality):
            raise RelationshipValidationError("Relationship changed; create a new candidate before checking it.")
        queries = verification_queries(
            source.dataset.schema, source.dataset.table_name, source.entry.column_name, target.dataset.schema, target.dataset.table_name, target.entry.column_name
        )
        live_type = {(dataset.id, str(column.column_name)): getattr(column, "type", None) for dataset in (source.dataset, target.dataset) for column in dataset.columns}
        type_match = types_match(
            live_type.get((source.dataset.id, source.entry.column_name)), live_type.get((target.dataset.id, target.entry.column_name))
        )
        try:
            with (
                source.dataset.database.get_sqla_engine(schema=source.dataset.schema) as engine,
                engine.connect() as connection,
                connection.begin(),
            ):
                if engine.dialect.name == "postgresql":
                    connection.execute(text(f"SET LOCAL statement_timeout = {VERIFICATION_TIMEOUT_MS}"))
                uniqueness = dict(connection.execute(queries["uniqueness"]).mappings().one())
                target_unique = (uniqueness.get("target_values") or 0) == (uniqueness.get("target_distinct") or 0)
                orphans = dict(connection.execute(queries["orphans"]).mappings().one()) if target_unique else None
                samples = connection.execute(queries["samples"]).scalars().all() if target_unique else []
        except Exception:
            logger.exception("Checking the relationship %s.%s failed", source.dataset.table_name, source.entry.column_name)
            contract.status = "candidate"
            contract.approver_id, contract.approved_at = None, None
            contract.verification, contract.verified_hash, contract.verified_at = None, None, None
            return None
        result = verification_result(uniqueness, orphans, list(samples), type_match)
        if not result.get("passed"):
            contract.status = "candidate"
            contract.approver_id, contract.approved_at = None, None
        contract.verification = json.dumps(result, ensure_ascii=False)
        contract.verified_hash = contract.contract_hash
        contract.verified_at = datetime.now(timezone.utc)
        return contract, source, target

    # -------------------------HELPER-------------------------
    def _context(self, dataset_id: int, column_id: int) -> tuple[RelationshipEnd, RelationshipEnd]:
        """Hai đầu của khóa ngoại trên URL, đã kiểm tra lực lượng."""
        entry = self.columns.read_in_dataset(dataset_id, column_id)
        if entry is None:
            raise ForeignKeyColumnNotFoundError()
        ends = relationship_ends(entry)
        if ends is None:
            raise RelationshipValidationError("The referenced dictionary column or dataset no longer exists.")
        relationship_cardinality(*ends)
        return ends

    def _snapshot_candidate(self, source: RelationshipEnd, target: RelationshipEnd, origin: str | None, actor_id: int) -> RelationshipContract | None:
        """Contract đề xuất chụp quan hệ như hiện tại; None khi đang có bản đã duyệt còn hiệu lực.

        Bản chụp mới xóa lượt duyệt, thu hồi và kết quả kiểm tra dữ liệu, vì chúng mô tả bản cũ.
        """
        cardinality = relationship_cardinality(source, target)
        contract_reader = getattr(self.contracts, "read_for_update", self.contracts.read_by_from_column)
        contract = contract_reader(source.dataset.id, source.entry.column_name)
        if contract is not None and relationship_is_approved_current(contract, source, target):
            return None
        # As for metric contracts, hash before a new contract joins the session so autoflush cannot insert it half-set.
        contract_hash = relationship_contract_hash(source, target, cardinality)
        snapshot = {
            "to_dataset_id": target.dataset.id,
            "to_column": target.entry.column_name,
            "cardinality": cardinality,
            "contract_hash": contract_hash,
            "source": origin or getattr(contract, "source", None) or "dictionary",
            "approver_id": None,
            "approved_at": None,
            "revoker_id": None,
            "revoked_at": None,
            "verification": None,
            "verified_hash": None,
            "verified_at": None,
            "status": "candidate",
        }
        if contract is None:
            return self.contracts.create({"from_dataset_id": source.dataset.id, "from_column": source.entry.column_name, "owner_id": actor_id, **snapshot})
        contract.owner_id = actor_id
        for field, value in snapshot.items():
            setattr(contract, field, value)
        return contract

    def _table_keys(self, dataset: SqlaTable) -> TableKeys:
        """Cột của một dataset vật lý và các cột từ điển tự giữ mỗi giá trị một lần."""
        live = {
            str(column.column_name): str(getattr(column, "type", None) or "")
            for column in dataset.columns
            if getattr(column, "is_active", None) is True and not getattr(column, "expression", None)
        }
        entries = [row for row in self.columns.read_by_dataset(dataset.id) if row.column_name in live]
        primary = [row.column_name for row in entries if row.is_pk]
        unique = {row.column_name for row in entries if row.is_unique} | (set(primary) if len(primary) == 1 else set())
        return TableKeys(dataset.id, dataset.schema, dataset.table_name, live, frozenset(unique))

    def _read_suggestions(self, dataset: SqlaTable, outgoing: list[dict[str, Any]]) -> dict[str, Any]:
        """Quan hệ được gợi ý đi ra từ dataset, chưa khai báo, và ghi chú khi không đọc được khóa ngoại của database."""
        from superset.sql.parse import Table

        tables = base_tables(dataset.database_id)
        keys = [self._table_keys(table_dataset) for table_dataset in tables]
        database_note = None
        try:
            foreign_keys = {dataset.id: dataset.database.get_foreign_keys(Table(dataset.table_name, dataset.schema))}
        except Exception:
            # The connection may not expose its catalog, or the account may not read it; names still suggest.
            logger.warning("Reading the foreign keys of %s failed", dataset.table_name, exc_info=True)
            foreign_keys, database_note = {}, "Không đọc được khoá ngoại từ database; chỉ gợi ý theo tên cột."
        declared = {(row["from_column"], row["to_dataset_id"], row["to_column"]) for row in outgoing}
        declared_columns = {row["from_column"] for row in outgoing}
        names = {table_dataset.id: table_dataset.table_name for table_dataset in tables}
        suggestions = [
            {**item, "to_dataset_name": names[item["to_dataset_id"]], "replaces": item["from_column"] in declared_columns}
            for item in merged_suggestions(database_suggestions(keys, foreign_keys), naming_suggestions(keys))
            if item["from_dataset_id"] == dataset.id and (item["from_column"], item["to_dataset_id"], item["to_column"]) not in declared
        ]
        return {"suggestions": suggestions, "suggestion_note": database_note}
