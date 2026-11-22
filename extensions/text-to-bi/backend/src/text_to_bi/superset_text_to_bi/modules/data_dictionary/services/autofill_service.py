from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import (
    column_type,
    dataset_columns,
    require_dataset,
)

from ..exceptions import (
    DataDictionaryValidationError,
    DictionaryAutofillFailedError,
    DictionaryAutofillInProgressError,
    DictionaryAutofillUnavailableError,
)
from ..models import ColumnDictionary, TableColumnRole, TableDictionary
from . import semantics
from .autofill_lock import AutofillLease, claim_autofill
from .dictionary_service import DataDictionaryService
from .dictionary_suggester import (
    ColumnSuggestion,
    ColumnSuggestions,
    DictionarySuggester,
    LlmDictionarySuggester,
    TableSuggestion,
)

COLUMN_BATCH_SIZE = 8
MAX_AUTOFILL_COLUMNS = 300


@dataclass(frozen=True)
class AutofillPlan:
    dataset_id: int
    table_context: dict[str, Any]
    lease: AutofillLease
    column_contexts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def batches(self) -> list[dict[str, Any]]:
        return [
            {**self.table_context, "columns": self.column_contexts[start:start + COLUMN_BATCH_SIZE]}
            for start in range(0, len(self.column_contexts), COLUMN_BATCH_SIZE)
        ]


@dataclass(frozen=True)
class AutofillEvent:
    name: str
    data: dict[str, Any]


def _clip(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    return value.strip()[:max_length] or None


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _checked_provider_error(error: Exception) -> None:
    status = getattr(error, "status_code", None)
    if status in (401, 403):
        raise DictionaryAutofillUnavailableError("Nhà cung cấp mô hình từ chối API key.") from error
    if status == 402:
        raise DictionaryAutofillUnavailableError("API key của nhà cung cấp mô hình đã hết hạn mức.") from error


# Fills only what is empty: a display name still equal to the physical name, and blank descriptions, business terms,
# units and grain. Each batch is written as soon as the model answers it, then reported as one event.
class DataDictionaryAutofillService:
    def __init__(self, session: Session, suggester: DictionarySuggester | None = None) -> None:
        self.session = session
        self.dictionary = DataDictionaryService(session)
        self.suggester = suggester or LlmDictionarySuggester()

    # Every check that can fail before the stream starts, so the client gets a plain HTTP error for them.
    def prepare(self, dataset: Any) -> AutofillPlan:
        current = self.dictionary.get_dataset_dictionary(dataset)
        columns = current["columns"]
        if not columns:
            raise DataDictionaryValidationError("Dataset chưa có cột nào để mô tả; hãy đồng bộ cột trong Superset.")
        if len(columns) > MAX_AUTOFILL_COLUMNS:
            raise DataDictionaryValidationError(f"Tự động điền hỗ trợ tối đa {MAX_AUTOFILL_COLUMNS} cột mỗi dataset.")
        try:
            self.suggester.ensure_ready()
        except RuntimeError as error:
            raise DictionaryAutofillUnavailableError() from error
        table_context = {
            "database_name": current["database_name"],
            "schema_name": current["schema_name"],
            "table_name": current["table_name"],
            "dataset_kind": current["dataset_kind"],
            "table_description": current["description"],
        }
        column_contexts = [
            {
                "column_name": column["column_name"],
                "data_type": column["data_type"],
                "superset_display_name": column["verbose_name"],
                "is_datetime": column["is_dttm"],
                "description": column["description"],
            }
            for column in columns
        ]
        lease = claim_autofill(self.session.get_bind(), dataset.id)
        if lease is None:
            raise DictionaryAutofillInProgressError()
        # The read transaction ends here so no connection sits idle in a transaction while the model answers.
        self.session.rollback()
        return AutofillPlan(dataset.id, table_context, lease, column_contexts)

    @staticmethod
    def release(plan: AutofillPlan) -> None:
        plan.lease.release()

    def events(self, plan: AutofillPlan) -> Iterator[AutofillEvent]:
        total = len(plan.column_contexts)
        batches = plan.batches
        yield AutofillEvent("status", {"processed": 0, "total": total, "message": "Đang chuẩn bị gợi ý"})

        suggestions: dict[str, ColumnSuggestion] = {}
        processed = failed = 0
        for index, result in self.suggester.suggest_column_batches(batches):
            names = [column["column_name"] for column in batches[index]["columns"]]
            processed += len(names)
            if isinstance(result, Exception):
                _checked_provider_error(result)
                failed += len(names)
                continue
            accepted = self._accepted(result, names)
            failed += len(names) - len(accepted)
            suggestions.update(accepted)
            self._fill_columns(plan.dataset_id, accepted)
            yield AutofillEvent("columns", {
                "columns": self._describe_columns(plan.dataset_id, set(accepted)),
                "processed": processed,
                "total": total,
            })

        yield AutofillEvent("status", {"processed": processed, "total": total, "message": "Đang gợi ý mô tả bảng"})
        table_suggestion = self._suggest_table(plan, suggestions)
        if not suggestions and table_suggestion is None:
            raise DictionaryAutofillFailedError()
        if table_suggestion is not None:
            self._fill_table(plan.dataset_id, table_suggestion)
        yield AutofillEvent("table", self.dictionary.get_dataset_dictionary(require_dataset(plan.dataset_id)))
        yield AutofillEvent("done", {
            "processed": processed,
            "total": total,
            "failed_columns": failed,
            "table_filled": table_suggestion is not None,
        })

    @staticmethod
    def _accepted(result: ColumnSuggestions | None, names: list[str]) -> dict[str, ColumnSuggestion]:
        accepted: dict[str, ColumnSuggestion] = {}
        for suggestion in result.suggestions if result else []:
            if suggestion.column_name in names and _clip(suggestion.display_name, 255):
                accepted.setdefault(suggestion.column_name, suggestion)
        return accepted

    def _describe_columns(self, dataset_id: int, names: set[str]) -> list[dict[str, Any]]:
        if not names:
            return []
        columns = self.dictionary.get_dataset_dictionary(require_dataset(dataset_id))["columns"]
        return [column for column in columns if column["column_name"] in names]

    def _suggest_table(
        self, plan: AutofillPlan, column_suggestions: dict[str, ColumnSuggestion],
    ) -> TableSuggestion | None:
        columns = []
        for column in plan.column_contexts:
            suggestion = column_suggestions.get(column["column_name"])
            columns.append({
                **column,
                "display_name": suggestion.display_name if suggestion else column["superset_display_name"],
                "description": (suggestion.description if suggestion else None) or column["description"],
            })
        try:
            suggestion = self.suggester.suggest_table({**plan.table_context, "columns": columns})
        # The column batches are already saved, so any failure here only leaves the table level unfilled.
        except Exception as error:  # noqa: BLE001
            _checked_provider_error(error)
            return None
        if suggestion is None or not _clip(suggestion.display_name, 255):
            return None
        return suggestion

    # Each batch reads the rows again right before writing, so what a user saved meanwhile is kept.
    def _fill_columns(self, dataset_id: int, suggestions: dict[str, ColumnSuggestion]) -> None:
        if not suggestions:
            return
        dataset = require_dataset(dataset_id)
        columns = [column for column in dataset_columns(dataset) if column.column_name in suggestions]
        entries = self.dictionary.column_dictionaries.read_by_dataset_id(dataset_id)
        stored = {entry.column_name: entry for entry in entries}
        for column in columns:
            entry = stored.get(column.column_name)
            values = self._column_values(column, entry, suggestions[column.column_name])
            if entry is None:
                self.dictionary.column_dictionaries.create(
                    ColumnDictionary(dataset_id=dataset_id, column_name=column.column_name, **values)
                )
            elif values:
                self.dictionary.column_dictionaries.update(entry, values)

    # A new entry keeps what Superset already says (verbose name, description) over the model's suggestion.
    @staticmethod
    def _column_values(column: Any, entry: ColumnDictionary | None, suggestion: ColumnSuggestion) -> dict[str, Any]:
        display_name = _clip(suggestion.display_name, 255)
        description = _clip(suggestion.description, semantics.MAX_DESCRIPTION_LENGTH)
        business_term = _clip(suggestion.business_term, semantics.MAX_DESCRIPTION_LENGTH)
        unit = _clip(suggestion.unit, 128)
        if entry is None:
            return {
                "display_name": _clip(getattr(column, "verbose_name", None), 255) or display_name or column.column_name,
                "description": _clip(getattr(column, "description", None), semantics.MAX_DESCRIPTION_LENGTH)
                or description,
                "business_term": business_term,
                "unit": unit,
                "temporal_kind": semantics.default_temporal_kind(
                    column_type(column), bool(getattr(column, "is_dttm", False))
                ),
            }
        values: dict[str, Any] = {}
        if display_name and entry.display_name.strip() in ("", column.column_name):
            values["display_name"] = display_name
        if description and _is_blank(entry.description):
            values["description"] = description
        if business_term and _is_blank(entry.business_term):
            values["business_term"] = business_term
        if unit and _is_blank(entry.unit):
            values["unit"] = unit
        return values

    def _fill_table(self, dataset_id: int, suggestion: TableSuggestion) -> None:
        dataset = require_dataset(dataset_id)
        display_name = _clip(suggestion.display_name, 255)
        description = _clip(suggestion.description, semantics.MAX_DESCRIPTION_LENGTH)
        grain_description = _clip(suggestion.grain_description, semantics.MAX_DESCRIPTION_LENGTH)

        dictionary = self.dictionary.table_dictionaries.read_by_dataset_id(dataset_id)
        if dictionary is None:
            dictionary = self.dictionary.table_dictionaries.create(TableDictionary(
                dataset_id=dataset_id,
                display_name=display_name or dataset.table_name,
                description=_clip(dataset.description, semantics.MAX_DESCRIPTION_LENGTH) or description,
                grain_description=grain_description,
            ))
        else:
            values: dict[str, Any] = {}
            if display_name and dictionary.display_name.strip() in ("", dataset.table_name):
                values["display_name"] = display_name
            if description and _is_blank(dictionary.description):
                values["description"] = description
            if grain_description and _is_blank(dictionary.grain_description):
                values["grain_description"] = grain_description
            if values:
                self.dictionary.table_dictionaries.update(dictionary, values)
        self._fill_created_at(dictionary, dataset, suggestion.created_at_column)

    def _fill_created_at(self, dictionary: TableDictionary, dataset: Any, column_name: str | None) -> None:
        if not column_name:
            return
        roles = self.dictionary.column_roles.read_by_parent_ids([dictionary.id])
        if any(role.role == "created_at" for role in roles):
            return
        column = next((column for column in dataset_columns(dataset) if column.column_name == column_name), None)
        is_dttm = bool(getattr(column, "is_dttm", False))
        if column is None or semantics.default_temporal_kind(column_type(column), is_dttm) is None:
            return
        self.dictionary.column_roles.create(
            TableColumnRole(table_dictionary_id=dictionary.id, role="created_at", column_name=column.column_name)
        )\n