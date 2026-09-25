from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./vocibot.db"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    extraction_provider: str = "demo"
    stt_provider: str = "demo"
    diarization_provider: str = "demo"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
