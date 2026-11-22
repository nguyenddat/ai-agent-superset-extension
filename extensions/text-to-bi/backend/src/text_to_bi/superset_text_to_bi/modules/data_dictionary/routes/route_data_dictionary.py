import logging
from collections.abc import Iterator
from typing import Any

from flask import Response, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset.extensions import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_text_to_bi.common.base_exceptions import AppError
from text_to_bi.superset_text_to_bi.common.utils.type_formatters import sse_event
from text_to_bi.superset_text_to_bi.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION, OPENAPI_TAG
from text_to_bi.superset_text_to_bi.core.security import csrf_protected
from text_to_bi.superset_text_to_bi.core.validation import query_int, request_body
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import (
    can_edit,
    require_dataset_access,
    require_edit,
    require_view,
)
from text_to_bi.superset_text_to_bi.modules.superset.dependencies import requires_dataset

from ..dependencies import data_dictionary_autofill_service, data_dictionary_service
from ..migrations import ensure_data_dictionary_tables
from ..schemas.schema_data_dictionary import (
    ColumnDictionariesIn,
    ColumnDictionaryOut,
    DictionaryStatsOut,
    DictionarySummaryOut,
    TableDictionaryIn,
    TableDictionaryOut,
)
from ..services import DataDictionaryAutofillService
from ..services.autofill_service import AutofillEvent, AutofillPlan

logger = logging.getLogger(__name__)

AUTOFILL_FAILED_MESSAGE = "Không thể tạo gợi ý từ điển dữ liệu."


def dictionary_payload(dictionary: dict[str, Any], editable: bool) -> dict[str, Any]:
    return TableDictionaryOut.model_validate({**dictionary, "can_edit": editable}).model_dump(mode="json")


def autofill_event_payload(event: AutofillEvent) -> dict[str, Any]:
    if event.name == "table":
        return dictionary_payload(event.data, True)
    if event.name == "columns":
        columns = [ColumnDictionaryOut.model_validate(column) for column in event.data["columns"]]
        return {**event.data, "columns": [column.model_dump(mode="json") for column in columns]}
    return event.data


# Each event's rows are committed before the event is sent. After the stream has started an error can only be an
# `error` event; the batches already sent stay saved.
def autofill_stream(service: DataDictionaryAutofillService, plan: AutofillPlan) -> Iterator[str]:
    try:
        for event in service.events(plan):
            service.session.commit()
            yield sse_event(event.name, autofill_event_payload(event))
    except AppError as error:
        service.session.rollback()
        yield sse_event("error", {"code": error.code, "message": str(error)})
    except Exception:
        service.session.rollback()
        logger.exception("Data dictionary autofill failed (dataset_id=%s)", plan.dataset_id)
        yield sse_event("error", {"code": "dictionary_autofill_failed", "message": AUTOFILL_FAILED_MESSAGE})
    finally:
        service.release(plan)


@api(
    id="text_to_bi_data_dictionary_api",
    name="Text to BI data dictionary API",
    description="Reads and saves the business dictionary of Superset datasets and autofills it with a language model.",
    resource_name="data-dictionary",
)
class DataDictionaryAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    # -------------------------READ---------------------------
    @expose("/summary", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_summary(self):
        require_view()
        ensure_data_dictionary_tables()
        summary = data_dictionary_service().get_summary()
        return self.response(200, **DictionarySummaryOut.model_validate(summary).model_dump(mode="json"))

    @expose("/stats", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_stats(self):
        require_view()
        limit = query_int("limit", default=5, minimum=1, maximum=20)
        ensure_data_dictionary_tables()
        stats = data_dictionary_service().get_stats(limit)
        return self.response(200, **DictionaryStatsOut.model_validate(stats).model_dump(mode="json"))

    @expose("/datasets/<int:dataset_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    @requires_dataset
    def get_dataset_dictionary(self, dataset: Any):
        require_view()
        require_dataset_access(dataset)
        ensure_data_dictionary_tables()
        dictionary = data_dictionary_service().get_dataset_dictionary(dataset)
        return self.response(200, **dictionary_payload(dictionary, can_edit(dataset)))

    # -------------------------UPDATE-------------------------
    @expose("/datasets/<int:dataset_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_dataset
    def save_table_dictionary(self, dataset: Any):
        require_edit(dataset)
        body = request_body(TableDictionaryIn)
        ensure_data_dictionary_tables()
        dictionary = data_dictionary_service().save_table_dictionary(dataset, body.model_dump())
        db.session.commit()
        return self.response(200, **dictionary_payload(dictionary, True))

    @expose("/datasets/<int:dataset_id>/columns", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_dataset
    def save_column_dictionaries(self, dataset: Any):
        require_edit(dataset)
        body = request_body(ColumnDictionariesIn)
        ensure_data_dictionary_tables()
        items = [item.model_dump() for item in body.columns]
        dictionary = data_dictionary_service().save_column_dictionaries(dataset, items)
        db.session.commit()
        return self.response(200, **dictionary_payload(dictionary, True))

    @expose("/datasets/<int:dataset_id>/autofill", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    @requires_dataset
    def autofill_dataset_dictionary(self, dataset: Any):
        require_edit(dataset)
        ensure_data_dictionary_tables()
        service = data_dictionary_autofill_service()
        plan = service.prepare(dataset)
        try:
            events = autofill_stream(service, plan)
            response = Response(
                stream_with_context(events), mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        except BaseException:
            service.release(plan)
            raise
        # A client that leaves before the stream ends closes the generator; the lease is released either way.
        response.call_on_close(lambda: service.release(plan))
        return response
