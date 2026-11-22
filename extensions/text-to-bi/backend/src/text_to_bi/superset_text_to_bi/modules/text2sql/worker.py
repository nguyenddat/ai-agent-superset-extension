from uuid import UUID

from flask_login import login_user
from superset.extensions import celery_app, db

from text_to_bi.superset_text_to_bi.core.config import settings
from text_to_bi.superset_text_to_bi.modules.auth.models import User

from .dependencies import index_services, ingestion_service
from .migrations import ensure_text2sql_tables
from .repositories.ingestion_job_repository import IngestionJobRepository, retry_delay_seconds


@celery_app.task(
    bind=True,
    name="text_to_bi.text2sql.process_ingestion_job",
    max_retries=settings.text2sql_job_max_attempts,
)
def process_ingestion_job(task, job_id: str) -> dict[str, object] | None:
    from superset.tasks.celery_app import flask_app

    with flask_app.app_context():
        return _process_ingestion_job(task, job_id, flask_app)


def _process_ingestion_job(task, job_id: str, app) -> dict[str, object] | None:
    ensure_text2sql_tables()
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        return None

    repository = IngestionJobRepository(db.session)
    job = repository.claim(parsed_job_id)
    if job is None:
        return None
    database_id, topic = job.database_id, job.topic
    requested_by_user = db.session.get(User, job.requested_by_user_id) if job.requested_by_user_id else None
    db.session.commit()
    if requested_by_user is None:
        repository.fail(job, "Không tìm thấy người dùng Superset đã yêu cầu job.", settings.text2sql_job_max_attempts)
        db.session.commit()
        return None

    services = index_services()
    try:
        with app.test_request_context():
            login_user(requested_by_user)
            result = ingestion_service(services).sync(database_id, [topic])
        payload = {
            "database_id": result.database_id,
            "topics": list(result.topics),
            "total": result.total,
            "indexed": result.indexed,
            "unchanged": result.unchanged,
            "deleted": result.deleted,
        }
        repository.complete(job, payload)
        db.session.commit()
        return payload
    except Exception as error:
        db.session.rollback()
        job = repository.get(parsed_job_id)
        if job is None:
            raise
        repository.fail(job, str(error), settings.text2sql_job_max_attempts)
        should_retry = job.status == "pending"
        countdown = retry_delay_seconds(job.attempts)
        db.session.commit()
        if should_retry:
            raise task.retry(exc=error, countdown=countdown) from error
        raise
    finally:
        services.index.close()
        services.embedding.close()
