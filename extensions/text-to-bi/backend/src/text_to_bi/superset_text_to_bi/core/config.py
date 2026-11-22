from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # The OpenAI-compatible model behind AI autofill of the data dictionary.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "openai/gpt-6-luna"
    QDRANT_URL: str = "http://qdrant:6333"
    TEXT2SQL_COLLECTION: str = "text2sql_semantics_v1"
    TEXT2SQL_EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    TEXT2SQL_EMBEDDING_DIMENSIONS: int = Field(default=1536, ge=1)
    TEXT2SQL_QUERY_MAX_ROWS: int = Field(default=200, ge=1, le=5000)
    TEXT2SQL_AGENT_MAX_ROWS_TO_LLM: int = Field(default=50, ge=1, le=1000)
    TEXT2SQL_AGENT_MAX_STEPS: int = Field(default=12, ge=1, le=50)
    TEXT2SQL_TIMEZONE: str = "Asia/Ho_Chi_Minh"
    TEXT2SQL_CLARIFICATION_TTL_MINUTES: int = Field(default=1440, ge=5, le=43200)
    TEXT2SQL_RERANK_MODEL: str = "typesafe/jev-1.14"
    TEXT2SQL_RERANK_POOL: int = Field(default=20, ge=1, le=50)
    TEXT2SQL_RERANK_CONCURRENCY: int = Field(default=8, ge=1, le=16)
    TEXT2SQL_RERANK_TIMEOUT_SECONDS: float = Field(default=20.0, gt=0)
    TEXT2SQL_WORKER_CONCURRENCY: int = Field(default=4, ge=1, le=32)
    TEXT2SQL_WORKER_POLL_SECONDS: float = Field(default=2.0, gt=0)
    TEXT2SQL_JOB_MAX_ATTEMPTS: int = Field(default=3, ge=1)
    TEXT2SQL_JOB_TIMEOUT_SECONDS: int = Field(default=900, ge=30)
    TEXT2SQL_JOB_RETENTION_DAYS: int = Field(default=7, ge=1)
    TEXT2SQL_TOPIC_INTERVALS: str = ""
    CONVERSATION_MAX_STORED_ROWS: int = Field(default=200, ge=1, le=5000)
    TEXT2SQL_CHART_TYPES_ENABLED: str = ""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    def require_openrouter_api_key(self) -> str:
        if not self.OPENROUTER_API_KEY.strip():
            raise RuntimeError("OPENROUTER_API_KEY is required for AI autofill")
        return self.OPENROUTER_API_KEY

    @property
    def text2sql_embedding_model(self) -> str:
        return self.TEXT2SQL_EMBEDDING_MODEL

    @property
    def text2sql_embedding_dimensions(self) -> int:
        return self.TEXT2SQL_EMBEDDING_DIMENSIONS

    @property
    def qdrant_url(self) -> str:
        return self.QDRANT_URL

    @property
    def text2sql_collection(self) -> str:
        return self.TEXT2SQL_COLLECTION

    @property
    def text2sql_query_max_rows(self) -> int:
        return self.TEXT2SQL_QUERY_MAX_ROWS

    @property
    def text2sql_agent_max_rows_to_llm(self) -> int:
        return self.TEXT2SQL_AGENT_MAX_ROWS_TO_LLM

    @property
    def text2sql_agent_max_steps(self) -> int:
        return self.TEXT2SQL_AGENT_MAX_STEPS

    @property
    def text2sql_timezone(self) -> str:
        return self.TEXT2SQL_TIMEZONE

    @property
    def text2sql_clarification_ttl_minutes(self) -> int:
        return self.TEXT2SQL_CLARIFICATION_TTL_MINUTES

    @property
    def text2sql_rerank_model(self) -> str:
        return self.TEXT2SQL_RERANK_MODEL

    @property
    def text2sql_rerank_pool(self) -> int:
        return self.TEXT2SQL_RERANK_POOL

    @property
    def text2sql_rerank_concurrency(self) -> int:
        return self.TEXT2SQL_RERANK_CONCURRENCY

    @property
    def text2sql_rerank_timeout_seconds(self) -> float:
        return self.TEXT2SQL_RERANK_TIMEOUT_SECONDS

    @property
    def text2sql_worker_concurrency(self) -> int:
        return self.TEXT2SQL_WORKER_CONCURRENCY

    @property
    def text2sql_worker_poll_seconds(self) -> float:
        return self.TEXT2SQL_WORKER_POLL_SECONDS

    @property
    def text2sql_job_max_attempts(self) -> int:
        return self.TEXT2SQL_JOB_MAX_ATTEMPTS

    @property
    def text2sql_job_timeout_seconds(self) -> int:
        return self.TEXT2SQL_JOB_TIMEOUT_SECONDS

    @property
    def text2sql_job_retention_days(self) -> int:
        return self.TEXT2SQL_JOB_RETENTION_DAYS

    @property
    def text2sql_topic_intervals(self) -> str:
        return self.TEXT2SQL_TOPIC_INTERVALS

    @property
    def text2sql_chart_types(self) -> frozenset[str] | None:
        names = {name.strip() for name in self.TEXT2SQL_CHART_TYPES_ENABLED.split(",") if name.strip()}
        return frozenset(names | {"table"}) if names else None


settings = Settings()
