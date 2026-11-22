from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # The OpenAI-compatible model behind AI autofill of the data dictionary.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "openai/gpt-6-luna"

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    def require_openrouter_api_key(self) -> str:
        if not self.OPENROUTER_API_KEY.strip():
            raise RuntimeError("OPENROUTER_API_KEY is required for AI autofill")
        return self.OPENROUTER_API_KEY


settings = Settings()
