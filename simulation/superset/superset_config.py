import os

from superset.config import CeleryConfig as SupersetCeleryConfig

SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "local-development-secret-change-me")
SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://"
    f"{os.getenv('SUPERSET_DB_USER', 'superset')}:{os.getenv('SUPERSET_DB_PASSWORD', 'superset_dev_password')}"
    f"@superset-db:5432/{os.getenv('SUPERSET_DB', 'superset')}"
)

FEATURE_FLAGS = {
    "ENABLE_EXTENSIONS": True,
}
EXTENSIONS_PATH = "/app/superset_home/extensions"


class TextToBICeleryConfig(SupersetCeleryConfig):
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    imports = (*SupersetCeleryConfig.imports, "text_to_bi.superset_text_to_bi.modules.text2sql.worker")


CELERY_CONFIG = TextToBICeleryConfig

# Semantic Layer: when true, whoever proposes a metric or writes an expert rule cannot approve it themselves.
TEXT_TO_BI_REQUIRE_SECOND_REVIEWER = os.getenv("TEXT_TO_BI_REQUIRE_SECOND_REVIEWER", "false").lower() == "true"
