from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ai_mode: str = "demo"
    database_url: str = "sqlite:///./vocibot.db"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    # A cold 8B model plus a long consultation can take well over 30 s locally.
    ollama_timeout_seconds: float = 120.0
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    asr_cpu_threads: int = 6
    # Live preview re-transcribes the unsettled audio buffer every step.  A
    # segment is settled once a later one follows it or `holdback` seconds of
    # audio have passed after it; the buffer is force-settled at `max_buffer`.
    asr_live_step_seconds: float = 0.35
    # Live previews served at once by the shared engine; further sessions are
    # still recorded and fully transcribed after Stop.
    max_live_sessions: int = 4
    # Final transcription is split at pauses into pieces of about this length
    # so other clinicians' live previews are served in between.
    asr_final_chunk_seconds: float = 30.0
    # How long Stop waits for an in-flight live preview pass.
    asr_live_stop_grace_seconds: float = 5.0
    asr_live_holdback_seconds: float = 1.2
    asr_live_max_buffer_seconds: float = 8.0
    asr_finalization_timeout_seconds: float = 60.0
    # Each live worker owns its model.  Do not invoke one native CTranslate2
    # model concurrently: that is unsafe on the supported macOS runtime.
    asr_model_workers: int = 1
    silero_threshold: float = 0.5
    audio_sample_rate: int = 16_000
    audio_debug_dir: str = ""
    # Accounts and sign-in.
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    password_min_length: int = 10
    session_cookie_name: str = "vocibot_session"
    # True when served over HTTPS (clinic server); keeps the cookie off plain HTTP.
    session_cookie_secure: bool = False
    # Comma-separated browser origins allowed to call the API.
    allowed_origins: str = "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:3001,http://localhost:3001"

    @property
    def allowed_origin_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.allowed_origins.split(",") if origin.strip()]
    # Consultation audio kept for compliance, retrieval and re-transcription.
    recordings_dir: str = "recordings"
    # Recordings are captured as WAV, converted losslessly to FLAC after the
    # session, and shrunk to Opus (~10% of WAV) once older than this many
    # days.  0 keeps lossless FLAC forever.
    recording_opus_after_days: int = 30
    recording_maintenance_interval_hours: float = 6.0
    asr_min_speech_seconds: float = 0.5
    asr_vad_filter: bool = True
    asr_no_speech_threshold: float = 0.6
    asr_log_prob_threshold: float = -1.0
    asr_compression_ratio_threshold: float = 2.4
    asr_min_language_probability: float = 0.5
    asr_min_avg_logprob: float = -1.0
    asr_max_no_speech_probability: float = 0.6
    asr_max_compression_ratio: float = 2.4
    asr_initial_prompt: str = ""
    asr_beam_size: int = 1
    whisperx_model: str = "WAV2VEC2_ASR_LARGE_LV60K_960H"
    whisperx_enabled: bool = False
    pyannote_model: str = "pyannote/speaker-diarization-3.1"
    diarization_enabled: bool = False
    extraction_provider: str = "demo"
    # "auto" uses MLX Whisper on the Apple Silicon GPU when it is installed,
    # otherwise faster-whisper on the CPU.
    stt_provider: str = "auto"
    mlx_whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    indic_conformer_model_path: str = ""
    diarization_provider: str = "demo"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def resolved_stt_provider(self) -> str:
        if self.stt_provider != "auto":
            return self.stt_provider
        return "mlx_whisper" if mlx_whisper_available() else "whisper"


def mlx_whisper_available() -> bool:
    import importlib.util
    import platform

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    try:
        return importlib.util.find_spec("mlx_whisper") is not None
    except (ImportError, ValueError):
        return False


settings = Settings()
