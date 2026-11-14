from typing import Any

from sqlalchemy.exc import IntegrityError

from ..dependencies import glossary_group_repository, glossary_revision_repository, glossary_term_repository
from ..exceptions import (
    GlossaryConflictError,
    GlossaryTermGroupNotFoundError,
    GlossaryTermNotFoundError,
    GlossaryValidationError,
)
from ..models import GlossaryTerm, GlossaryTermGroup
from .srv_glossary_event import GlossaryEventService
from .srv_glossary_validation import normalize_group_payload
from .srv_group_suggestion import GLOSSARY_KIND, GroupingCandidate, dismiss_suggestion, grouping_choice, suggest_groups

GROUP_NAME_TAKEN = "Đã có nhóm thuật ngữ cùng tên."
UNGROUPED = "Chưa phân nhóm"


class GlossaryGroupService:
    def __init__(self) -> None:
        self.groups = glossary_group_repository()
        self.terms = glossary_term_repository()
        self.revisions = glossary_revision_repository()
        self.events = GlossaryEventService()

    # -------------------------CREATE-------------------------
    def create(self, payload: Any) -> GlossaryTermGroup:
        values = normalize_group_payload(payload)
        if self.groups.read_by_normalized_name(values["normalized_name"]) is not None:
            raise GlossaryConflictError(GROUP_NAME_TAKEN)
        try:
            return self.groups.create(values)
        except IntegrityError as error:
            raise GlossaryConflictError(GROUP_NAME_TAKEN) from error

    # -------------------------READ---------------------------
    def read_all(self) -> list[GlossaryTermGroup]:
        return self.groups.read_all()

    def require(self, group_id: int) -> GlossaryTermGroup:
        group = self.groups.read(group_id)
        if group is None:
            raise GlossaryTermGroupNotFoundError()
        return group

    # -------------------------UPDATE-------------------------
    def update(self, group_id: int, payload: Any) -> GlossaryTermGroup:
        """Đổi tên hoặc mô tả nhóm; thuật ngữ trong nhóm giữ nguyên và không cần duyệt lại."""
        group = self.require(group_id)
        values = normalize_group_payload(payload)
        same_name = self.groups.read_by_normalized_name(values["normalized_name"])
        if same_name is not None and same_name.id != group.id:
            raise GlossaryConflictError(GROUP_NAME_TAKEN)
        try:
            return self.groups.update(group, values)
        except IntegrityError as error:
            raise GlossaryConflictError(GROUP_NAME_TAKEN) from error

    def move_term(self, term_id: int, group_id: int | None, actor_id: int) -> GlossaryTerm:
        """Chuyển thuật ngữ vào nhóm, hoặc bỏ khỏi mọi nhóm khi `group_id` là None."""
        term = self.terms.read_for_update(term_id)
        if term is None:
            raise GlossaryTermNotFoundError()
        self.place_term(term, None if group_id is None else self.require(group_id), actor_id)
        return term

    def place_term(self, term: GlossaryTerm, group: GlossaryTermGroup | None, actor_id: int) -> None:
        """Đặt thuật ngữ vào nhóm và ghi sự kiện `moved`; không cần duyệt, bản đã duyệt vẫn được dùng."""
        previous = term.group
        if (previous.id if previous else None) == (group.id if group else None):
            return
        term.group = group
        term.group_id = group.id if group else None
        revision = self.revisions.read_current(term.id)
        if revision is None:
            return
        reason = f"{previous.name if previous else UNGROUPED} → {group.name if group else UNGROUPED}"
        self.events.create(revision, "moved", actor_id, reason)

    # -------------------------DELETE-------------------------
    def delete(self, group_id: int, actor_id: int) -> list[int]:
        """Xóa nhóm, các thuật ngữ trong nhóm thành chưa phân nhóm; trả về ID các thuật ngữ đã chuyển."""
        group = self.require(group_id)
        terms = self.terms.read_in_group(group.id)
        for term in terms:
            self.place_term(term, None, actor_id)
        self.groups.delete(group)
        return [term.id for term in terms]

    # -------------------------SUGGESTION---------------------
    def suggest(self) -> dict[str, Any]:
        """Gợi ý nhóm cho thuật ngữ chưa phân nhóm có nghĩa gần nhau, đọc từ bản hiện tại."""
        candidates = []
        for term in self.terms.read_all():
            revision = self.revisions.read_current(term.id)
            if revision is not None:
                text = term_text(term.canonical_name, revision.synonyms or [], revision.definition)
                candidates.append(GroupingCandidate(term.id, term.canonical_name, text, term.group_id))
        group_names = {group.id: group.name for group in self.groups.read_all()}
        return suggest_groups(GLOSSARY_KIND, candidates, group_names)

    def apply_suggestion(self, payload: Any, actor_id: int) -> tuple[GlossaryTermGroup, list[int]]:
        """Chuyển các thuật ngữ quản trị viên giữ lại vào nhóm có sẵn hoặc nhóm mới; trả về nhóm và ID thuật ngữ."""
        choice = grouping_choice(payload, GlossaryValidationError)
        if choice.group_id is not None:
            group = self.require(choice.group_id)
        else:
            group = self.create({"name": choice.group_name})
        return group, [self.move_term(term_id, group.id, actor_id).id for term_id in choice.member_ids]

    @staticmethod
    def dismiss_suggestion(payload: Any, actor_id: int) -> str:
        """Bỏ qua một gợi ý để không gợi ý lại; trả về fingerprint."""
        return dismiss_suggestion(GLOSSARY_KIND, payload, actor_id, GlossaryValidationError)


def term_text(canonical_name: str, synonyms: list[str], definition: str) -> str:
    """Nghĩa của thuật ngữ để embedding: tên, từ đồng nghĩa và định nghĩa.

    Links are left out: they say where the data lives, and terms on one dataset would look alike for that alone.
    """
    synonym_text = f" Đồng nghĩa: {'; '.join(synonyms)}." if synonyms else ""
    return f"{canonical_name}.{synonym_text} {definition}"
