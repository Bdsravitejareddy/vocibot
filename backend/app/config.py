from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ai_mode: str = "demo"
    database_url: str = "sqlite:///./vocibot.db"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    silero_threshold: float = 0.5
    audio_sample_rate: int = 16_000
    whisperx_model: str = "WAV2VEC2_ASR_LARGE_LV60K_960H"
    whisperx_enabled: bool = False
    pyannote_model: str = "pyannote/speaker-diarization-3.1"
    diarization_enabled: bool = False
    extraction_provider: str = "demo"
    stt_provider: str = "demo"
    diarization_provider: str = "demo"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
