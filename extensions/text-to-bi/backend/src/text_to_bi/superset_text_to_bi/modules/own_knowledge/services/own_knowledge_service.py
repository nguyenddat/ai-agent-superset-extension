import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.common.utils.type_formatters import utc_now
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import (
    current_user_id,
    require_admin,
    require_dataset_access,
)
from text_to_bi.superset_text_to_bi.modules.expert_rule_management.models import ExpertRule
from text_to_bi.superset_text_to_bi.modules.expert_rule_management.schemas.schema_expert_rule import RuleCreate
from text_to_bi.superset_text_to_bi.modules.expert_rule_management.services import ExpertRuleService
from text_to_bi.superset_text_to_bi.modules.glossary_management.models import GlossaryTerm
from text_to_bi.superset_text_to_bi.modules.glossary_management.schemas.schema_glossary import GlossaryCreate
from text_to_bi.superset_text_to_bi.modules.glossary_management.services import GlossaryService
from text_to_bi.superset_text_to_bi.modules.metric_management.models import Metric
from text_to_bi.superset_text_to_bi.modules.metric_management.schemas.schema_metric import MetricCreate
from text_to_bi.superset_text_to_bi.modules.metric_management.services import MetricService
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import (
    get_datasets,
)
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import (
    require_dataset as get_dataset,
)

from ..exceptions import OwnKnowledgeConflictError, OwnKnowledgeNotFoundError, OwnKnowledgeValidationError
from ..models import OwnClarification, OwnKnowledgeEntry, OwnProposal
from ..repositories import OwnKnowledgeRepository

KNOWLEDGE_KINDS = {"glossary", "metric", "expert_rule"}
REVIEW_STATUSES = {"pending", "kept_own", "promoted"}


class OwnKnowledgeService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = OwnKnowledgeRepository(session)

    def push_clarification(self, values: dict[str, Any]) -> dict[str, Any]:
        dataset_id = values["dataset_id"]
        self._dataset(dataset_id)
        user_id = current_user_id()
        key = self._text(values["idempotency_key"], 128)
        question = self._text(values["question"], 10000)
        missing = sorted(set(values["missing"]))
        if len(missing) != len(values["missing"]) or not set(missing) <= KNOWLEDGE_KINDS:
            raise OwnKnowledgeValidationError("Loại nội dung thiếu bị trùng hoặc không hợp lệ.")
        proposals = []
        seen: set[tuple[str, str]] = set()
        for raw in values["proposals"]:
            item = raw if isinstance(raw, dict) else raw.model_dump()
            kind = item["kind"]
            name = self._name(item["name"], 255)
            key_name = (kind, name.casefold())
            if kind not in missing or key_name in seen:
                raise OwnKnowledgeValidationError("Đề xuất trùng hoặc không thuộc loại nội dung thiếu.")
            seen.add(key_name)
            options = [self._text(option, 2000) for option in item["options"]]
            if not options or len(options) > 10 or len({option.casefold() for option in options}) != len(options):
                raise OwnKnowledgeValidationError("Phương án làm rõ trùng hoặc không hợp lệ.")
            proposal_dataset_id = item.get("dataset_id")
            if proposal_dataset_id is not None and proposal_dataset_id != dataset_id:
                raise OwnKnowledgeValidationError("Dataset đề xuất không khớp dataset câu hỏi.")
            proposals.append({
                "kind": kind, "name": name, "normalized_name": name.casefold(),
                "concept": self._optional_text(item.get("concept"), 255),
                "prompt": self._text(item["prompt"], 2000), "options": options,
                "dataset_id": proposal_dataset_id,
            })
        canonical = {
            "user_id": user_id, "dataset_id": dataset_id, "idempotency_key": key,
            "source_session_id": self._optional_text(values.get("source_session_id"), 255),
            "source_question_id": self._optional_text(values.get("source_question_id"), 255),
            "question": question, "missing": missing, "proposals": proposals,
        }
        fingerprint = self._fingerprint(canonical)
        existing = self.repository.clarifications.by_key(dataset_id, user_id, key)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise OwnKnowledgeConflictError("Idempotency key đã dùng cho nội dung khác.")
            return self._clarification(existing)
        try:
            with self.session.begin_nested():
                clarification = OwnClarification(
                    dataset_id=dataset_id, user_id=user_id, idempotency_key=key,
                    source_session_id=canonical["source_session_id"],
                    source_question_id=canonical["source_question_id"], question=question, missing=missing,
                    status="pending", request_fingerprint=fingerprint,
                )
                self.session.add(clarification)
                self.session.flush()
                for item in proposals:
                    self.session.add(OwnProposal(clarification_id=clarification.id, **item))
                self.session.flush()
        except IntegrityError as error:
            existing = self.repository.clarifications.by_key(dataset_id, user_id, key)
            if existing is None or existing.request_fingerprint != fingerprint:
                raise OwnKnowledgeConflictError("Idempotency key hoặc đề xuất đã tồn tại.") from error
            return self._clarification(existing)
        return self._clarification(clarification)

    def get_clarification(self, clarification_id: UUID) -> dict[str, Any]:
        return self._clarification(self._own_clarification(clarification_id))

    def answer_clarification(self, clarification_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        clarification = self._own_clarification(clarification_id, lock=True)
        proposals = {item.id: item for item in self.repository.proposals.list_for_clarification(clarification.id)}
        answers = []
        seen: set[UUID] = set()
        for raw in values["answers"]:
            answer = raw if isinstance(raw, dict) else raw.model_dump()
            proposal_id = answer["proposal_id"]
            if proposal_id in seen or proposal_id not in proposals:
                raise OwnKnowledgeValidationError("Phương án xác nhận không thuộc câu hỏi hoặc bị trùng.")
            seen.add(proposal_id)
            proposal = proposals[proposal_id]
            option_index = answer.get("option_index")
            if option_index is not None:
                if option_index >= len(proposal.options):
                    raise OwnKnowledgeValidationError("Chỉ số phương án làm rõ không hợp lệ.")
                definition = proposal.options[option_index]
            else:
                definition = self._text(answer["definition"], 2000)
            answers.append({"proposal_id": str(proposal_id), "definition": definition})
        answers.sort(key=lambda item: item["proposal_id"])
        fingerprint = self._fingerprint({"state": values["state"], "answers": answers})
        if clarification.status != "pending":
            if clarification.answer_fingerprint != fingerprint:
                raise OwnKnowledgeConflictError("Câu hỏi đã được trả lời bằng nội dung khác.")
            return self._answer_result(clarification)
        confirmed_entries = []
        if values["state"] == "confirmed":
            for answer in answers:
                proposal = proposals[UUID(answer["proposal_id"])]
                entry = self.repository.entries.own_entry(
                    clarification.dataset_id, clarification.user_id, proposal.kind, proposal.normalized_name,
                )
                if entry is None:
                    entry = OwnKnowledgeEntry(
                        dataset_id=clarification.dataset_id, user_id=clarification.user_id,
                        kind=proposal.kind, normalized_name=proposal.normalized_name,
                    )
                    self.session.add(entry)
                else:
                    entry.version += 1
                entry.name = proposal.name
                entry.concept = proposal.concept
                entry.definition = answer["definition"]
                entry.source_clarification_id = clarification.id
                entry.source_proposal_id = proposal.id
                self._reopen(entry)
                confirmed_entries.append(entry)
        try:
            self.session.flush()
        except IntegrityError as error:
            raise OwnKnowledgeConflictError("Nội dung cùng tên đã được ghi nhận đồng thời.") from error
        clarification.confirmed_entry_ids = [str(entry.id) for entry in confirmed_entries]
        clarification.status = values["state"]
        clarification.answer_fingerprint = fingerprint
        clarification.answered_at = utc_now()
        self.session.flush()
        return self._answer_result(clarification)

    def agent_entries(self, dataset_id: int) -> list[dict[str, Any]]:
        self._dataset(dataset_id)
        return [
            self._entry(entry)
            for entry in self.repository.entries.own_entries(dataset_id, current_user_id())
            if self._active_for_agent(entry)
        ]

    def update_own_entry(self, entry_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        entry = self._own_entry(entry_id, lock=True)
        self._expected(entry, values["expected_version"])
        name = self._name(values["name"], 255)
        duplicate = self.repository.entries.own_entry(
            entry.dataset_id, entry.user_id, entry.kind, name.casefold(),
        )
        if duplicate is not None and duplicate.id != entry.id:
            raise OwnKnowledgeConflictError("Nội dung riêng cùng tên đã tồn tại.")
        entry.name = name
        entry.normalized_name = name.casefold()
        entry.concept = self._optional_text(values.get("concept"), 255)
        entry.definition = self._text(values["definition"], 2000)
        entry.version += 1
        self._reopen(entry)
        try:
            self.session.flush()
        except IntegrityError as error:
            raise OwnKnowledgeConflictError("Nội dung riêng cùng tên đã tồn tại.") from error
        return self._entry(entry)

    def delete_own_entry(self, entry_id: UUID) -> None:
        self.session.delete(self._own_entry(entry_id, lock=True))
        self.session.flush()

    def review_entries(
        self, dataset_id: int | None, status: str | None, user_id: int | None,
    ) -> list[dict[str, Any]]:
        require_admin()
        if dataset_id is not None:
            self._dataset(dataset_id)
        if status is not None and status not in REVIEW_STATUSES:
            raise OwnKnowledgeValidationError("Trạng thái review không hợp lệ.")
        rows = self.repository.entries.review_entries(dataset_id, status, user_id)
        accessible_ids = {item.id for item in get_datasets({row.dataset_id for row in rows})}
        return [
            self._entry(entry)
            for entry in rows if entry.dataset_id in accessible_ids
        ]

    def get_admin_entry(self, entry_id: UUID) -> dict[str, Any]:
        require_admin()
        entry = self._get_entry(entry_id)
        self._dataset(entry.dataset_id)
        return self._entry(entry)

    def review_entry(self, entry_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        require_admin()
        entry = self._get_entry(entry_id, lock=True)
        self._dataset(entry.dataset_id)
        self._expected(entry, values["expected_version"])
        entry.review_status = "kept_own" if values["action"] == "keep_own" else "pending"
        entry.review_note = self._optional_text(values.get("note"), 1000)
        entry.reviewed_by = current_user_id()
        entry.reviewed_at = utc_now()
        entry.promoted_kind = None
        entry.promoted_id = None
        entry.version += 1
        entry.updated_at = utc_now()
        self.session.flush()
        return self._entry(entry)

    def promote_entry(self, entry_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        require_admin()
        entry = self._get_entry(entry_id, lock=True)
        self._expected(entry, values["expected_version"])
        if entry.review_status == "promoted":
            raise OwnKnowledgeConflictError("Nội dung đã được chuyển thành bản ghi hệ thống.")
        kind = values["target_kind"]
        payload = values["payload"]
        if not isinstance(payload, dict):
            raise OwnKnowledgeValidationError("Payload hệ thống không hợp lệ.")
        dataset = self._dataset(entry.dataset_id)
        try:
            if kind == "glossary":
                body = GlossaryCreate.model_validate({**payload, "dataset_id": dataset.id})
                saved = GlossaryService(self.session).create_term(body.model_dump())
            elif kind == "metric":
                body = MetricCreate.model_validate({**payload, "dataset_id": dataset.id})
                saved = MetricService(self.session).create_metric(body.model_dump())
            else:
                body = RuleCreate.model_validate({**payload, "dataset_id": dataset.id})
                saved = ExpertRuleService(self.session).create_rule(body.model_dump())
        except PydanticValidationError as error:
            raise OwnKnowledgeValidationError("Payload hệ thống không hợp lệ.") from error
        entry.review_status = "promoted"
        entry.review_note = self._optional_text(values.get("note"), 1000)
        entry.reviewed_by = current_user_id()
        entry.reviewed_at = utc_now()
        entry.promoted_kind = kind
        entry.promoted_id = UUID(str(saved["id"]))
        entry.version += 1
        entry.updated_at = utc_now()
        self.session.flush()
        return {"entry": self._entry(entry), "target": saved}

    def _active_for_agent(self, entry: OwnKnowledgeEntry) -> bool:
        if entry.review_status != "promoted" or entry.promoted_id is None:
            return True
        if entry.promoted_kind == "glossary":
            term = self.session.get(GlossaryTerm, entry.promoted_id)
            return term is None or GlossaryService(self.session).serving_revision(term.id) is None
        if entry.promoted_kind == "metric":
            metric = self.session.get(Metric, entry.promoted_id)
            return (
                metric is None or metric.dataset_id != entry.dataset_id
                or not metric.is_active or metric.status != "approved"
            )
        if entry.promoted_kind == "expert_rule":
            rule = self.session.get(ExpertRule, entry.promoted_id)
            return rule is None or rule.dataset_id != entry.dataset_id or not any(
                item["id"] == rule.id for item in ExpertRuleService(self.session).discovery(entry.dataset_id)
            )
        return True

    def _dataset(self, dataset_id: int) -> Any:
        dataset = get_dataset(dataset_id)
        if dataset is None:
            raise OwnKnowledgeNotFoundError("Không tìm thấy dataset.")
        require_dataset_access(dataset)
        return dataset

    def _own_clarification(self, clarification_id: UUID, lock: bool = False) -> OwnClarification:
        clarification = self.repository.clarifications.get(clarification_id, lock)
        if clarification is None or clarification.user_id != current_user_id():
            raise OwnKnowledgeNotFoundError()
        self._dataset(clarification.dataset_id)
        return clarification

    def _get_entry(self, entry_id: UUID, lock: bool = False) -> OwnKnowledgeEntry:
        entry = self.repository.entries.get(entry_id, lock)
        if entry is None:
            raise OwnKnowledgeNotFoundError()
        return entry

    def _own_entry(self, entry_id: UUID, lock: bool = False) -> OwnKnowledgeEntry:
        entry = self._get_entry(entry_id, lock)
        if entry.user_id != current_user_id():
            raise OwnKnowledgeNotFoundError()
        self._dataset(entry.dataset_id)
        return entry

    def _clarification(self, row: OwnClarification) -> dict[str, Any]:
        return {
            "id": row.id, "user_id": row.user_id, "dataset_id": row.dataset_id,
            "idempotency_key": row.idempotency_key, "source_session_id": row.source_session_id,
            "source_question_id": row.source_question_id, "question": row.question, "missing": row.missing,
            "status": row.status,
            "proposals": [{
                "id": item.id, "kind": item.kind, "name": item.name, "concept": item.concept,
                "prompt": item.prompt, "options": item.options, "dataset_id": item.dataset_id,
            } for item in self.repository.proposals.list_for_clarification(row.id)],
            "created_at": row.created_at, "answered_at": row.answered_at,
        }

    def _answer_result(self, clarification: OwnClarification) -> dict[str, Any]:
        entries = [
            self.repository.entries.get(UUID(entry_id))
            for entry_id in clarification.confirmed_entry_ids
        ]
        return {
            "clarification": self._clarification(clarification),
            "entries": [self._entry(entry) for entry in entries if entry is not None],
        }

    def _entry(self, row: OwnKnowledgeEntry) -> dict[str, Any]:
        source = (
            self.repository.clarifications.get(row.source_clarification_id)
            if row.source_clarification_id else None
        )
        return {
            "id": row.id, "dataset_id": row.dataset_id, "user_id": row.user_id,
            "kind": row.kind, "name": row.name, "concept": row.concept, "definition": row.definition,
            "source_clarification_id": row.source_clarification_id, "source_proposal_id": row.source_proposal_id,
            "source_question": source.question if source else None,
            "review_status": row.review_status, "review_note": row.review_note,
            "reviewed_by": row.reviewed_by, "reviewed_at": row.reviewed_at,
            "promoted_kind": row.promoted_kind, "promoted_id": row.promoted_id, "version": row.version,
            "created_at": row.created_at, "updated_at": row.updated_at,
            "active_for_agent": self._active_for_agent(row),
        }

    @staticmethod
    def _expected(entry: OwnKnowledgeEntry, expected: int) -> None:
        if entry.version != expected:
            raise OwnKnowledgeConflictError()

    @staticmethod
    def _reopen(entry: OwnKnowledgeEntry) -> None:
        entry.review_status = "pending"
        entry.review_note = None
        entry.reviewed_by = None
        entry.reviewed_at = None
        entry.promoted_kind = None
        entry.promoted_id = None
        entry.updated_at = utc_now()

    @staticmethod
    def _text(value: str, maximum: int) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > maximum:
            raise OwnKnowledgeValidationError("Văn bản trống hoặc vượt quá giới hạn.")
        return normalized

    @classmethod
    def _name(cls, value: str, maximum: int) -> str:
        return " ".join(cls._text(value, maximum).split())

    @classmethod
    def _optional_text(cls, value: str | None, maximum: int) -> str | None:
        return cls._text(value, maximum) if value and value.strip() else None

    @staticmethod
    def _fingerprint(value: Any) -> str:
        packed = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        return hashlib.sha256(packed.encode("utf-8")).hexdigest()
