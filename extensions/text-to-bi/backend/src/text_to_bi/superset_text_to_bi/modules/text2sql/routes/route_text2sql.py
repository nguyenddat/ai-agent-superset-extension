import asyncio
import queue
import threading

from flask import Response, copy_current_request_context, request, stream_with_context
from flask_appbuilder.api import expose, permission_name, protect, safe
from superset.extensions import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_text_to_bi.common.charts import (
    ChartField,
    ChartSpecError,
    chart_catalog,
    compatible_types,
)
from text_to_bi.superset_text_to_bi.common.charts import (
    validate_chart as validate_chart_spec,
)
from text_to_bi.superset_text_to_bi.core.config import settings
from text_to_bi.superset_text_to_bi.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION, OPENAPI_TAG
from text_to_bi.superset_text_to_bi.core.security import csrf_protected
from text_to_bi.superset_text_to_bi.core.validation import request_body
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import (
    current_user_id,
    require_admin,
    require_query,
)
from text_to_bi.superset_text_to_bi.modules.management_payload import json_payload
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import datasets_on_database, get_database

from ..dependencies import (
    chat_service_factory,
    index_services,
    ingestion_job_repository,
    ingestion_service,
    retrieval_service,
)
from ..migrations import ensure_text2sql_tables
from ..models.ingestion_job import FAILED, MANUAL, PENDING, RUNNING, SUCCEEDED, SUPERSEDED
from ..schemas import ChartValidateIn, JobEnqueueIn, JobOut, RetrieveIn, SyncIn, SyncOut
from ..utils.exceptions import Text2SqlChartInvalid, Text2SqlConnectionNotFound, Text2SqlInvalidRequest
from ..utils.topics import TOPICS

JOB_STATUSES = (PENDING, RUNNING, SUCCEEDED, FAILED, SUPERSEDED)


async def _is_disconnected(disconnected: threading.Event) -> bool:
    return disconnected.is_set()


def _database(database_id: int):
    database = get_database(database_id)
    if database is None:
        raise Text2SqlConnectionNotFound()
    if getattr(getattr(database, "db_engine_spec", None), "engine", None) != "postgresql":
        raise Text2SqlInvalidRequest("Text2SQL hiện hỗ trợ database PostgreSQL qua SQL Lab của Superset.")
    require_query_dataset = False
    for dataset in datasets_on_database(database_id):
        require_query(dataset)
        require_query_dataset = True
    if not require_query_dataset:
        raise Text2SqlInvalidRequest("Superset database chưa có dataset được cấp quyền truy vấn.")
    return database


def _database_id(payload: object) -> int:
    database_id = getattr(payload, "database_id", None)
    if isinstance(database_id, bool) or not isinstance(database_id, int) or database_id < 1:
        raise Text2SqlInvalidRequest("database_id phải là ID database Superset dương.")
    _database(database_id)
    return database_id


@api(
    id="text_to_bi_text2sql_api",
    name="Text to BI Text2SQL API",
    description="Answers natural-language questions using Superset datasets and SQL Lab.",
    resource_name="text2sql",
)
class Text2SqlAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    @expose("/chat", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def chat(self):
        from ..schemas import ChatIn

        body = request_body(ChatIn)
        database_id = _database_id(body)
        ensure_text2sql_tables()
        with chat_service_factory() as service:
            result = service.chat(
                database_id, body.question, body.chat_history, current_user_id(), body.conversation_id, body.resume_id,
            )
        return self.response(200, result=json_payload(result))

    @expose("/chat/stream", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @handle_errors
    def chat_stream(self):
        from ..schemas import ChatIn
        from ..services.chat_stream import ChatStream, error_payload, sse

        body = request_body(ChatIn)
        _database_id(body)
        ensure_text2sql_tables()
        user_id = current_user_id()
        events: queue.Queue[str | None] = queue.Queue()
        disconnected = threading.Event()

        def produce() -> None:
            async def stream_events() -> None:
                stream = ChatStream(
                    chat_service_factory,
                    body,
                    user_id,
                    lambda: _is_disconnected(disconnected),
                )
                try:
                    await stream.start()
                    async for event in stream.events():
                        events.put(event)
                except Exception as error:  # noqa: BLE001 - stream failures must become an SSE error event.
                    events.put(sse("error", error_payload(error)))
                finally:
                    stream.stopped.set()
                    events.put(None)

            asyncio.run(stream_events())

        def response_events():
            stream_worker = copy_current_request_context(produce)
            threading.Thread(target=stream_worker, name="text2sql-chat-stream", daemon=True).start()
            try:
                while True:
                    event = events.get()
                    if event is None:
                        return
                    yield event
            finally:
                disconnected.set()

        response = Response(
            stream_with_context(response_events()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        return response

    @expose("/chart-types", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def chart_types(self):
        return self.response(200, result=chart_catalog(settings.text2sql_chart_types))

    @expose("/charts/validate", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @handle_errors
    def validate_chart(self):
        body = request_body(ChartValidateIn)
        fields = [ChartField.model_validate(field.model_dump()) for field in body.fields]
        try:
            chart = validate_chart_spec(
                body.chart,
                fields,
                body.rows,
                rows_complete=body.rows_complete,
                enabled=settings.text2sql_chart_types,
            )
        except ChartSpecError as error:
            raise Text2SqlChartInvalid("\n".join(error.errors)) from None
        return self.response(200, chart=chart.json(), warnings=chart.warnings, chart_types=compatible_types(
            fields, body.rows, enabled=settings.text2sql_chart_types, rows_complete=body.rows_complete,
        ))

    @expose("/retrieve", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def retrieve(self):
        body = request_body(RetrieveIn)
        database_id = _database_id(body)
        services = index_services()
        try:
            candidates = retrieval_service(services).top_metrics(database_id, body.question, body.k)
            return self.response(200, candidates=json_payload(candidates))
        finally:
            services.index.close()
            services.embedding.close()

    @expose("/ingestion/sync", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def sync_index(self):
        require_admin()
        body = request_body(SyncIn)
        database_id = _database_id(body)
        ensure_text2sql_tables()
        services = index_services()
        try:
            result = ingestion_service(services).sync(database_id, body.topics or TOPICS)
            db.session.commit()
            return self.response(200, result=json_payload(SyncOut(
                database_id=database_id, topics=list(result.topics), total=result.total,
                indexed=result.indexed, unchanged=result.unchanged, deleted=result.deleted,
            )))
        finally:
            services.index.close()
            services.embedding.close()

    @expose("/ingestion/jobs", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def enqueue_ingestion(self):
        require_admin()
        body = request_body(JobEnqueueIn)
        database_id = _database_id(body)
        ensure_text2sql_tables()
        topics = body.topics or list(TOPICS)
        repository = ingestion_job_repository()
        repository.enqueue([database_id], topics, MANUAL, requested_by_user_id=current_user_id())
        db.session.commit()
        from ..worker import process_ingestion_job

        for job in repository.list_recent(database_id, PENDING, limit=200):
            if job.topic in topics:
                process_ingestion_job.delay(str(job.id))
        return self.response(202, database_id=database_id, topics=topics)

    @expose("/ingestion/jobs", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_ingestion_jobs(self):
        require_admin()
        ensure_text2sql_tables()
        database_id = request.args.get("database_id", type=int)
        if database_id is not None:
            _database(database_id)
        status = request.args.get("status")
        limit = request.args.get("limit", default=50, type=int)
        if not 1 <= limit <= 200 or (status is not None and status not in JOB_STATUSES):
            raise Text2SqlInvalidRequest("limit hoặc status không hợp lệ.")
        jobs = ingestion_job_repository().list_recent(database_id, status, limit)
        return self.response(200, result=json_payload([JobOut.model_validate(job) for job in jobs]))
