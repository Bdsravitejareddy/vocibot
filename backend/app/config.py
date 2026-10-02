from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ai_mode: str = "demo"
    database_url: str = "sqlite:///./vocibot.db"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    # Two model workers with six native threads each keep pace with 450 ms live
    # windows on the target 14-core Apple Silicon machine without oversubscription.
    asr_cpu_threads: int = 6
    asr_parallel_workers: int = 2
    asr_reserve_workers: int = 0
    asr_live_stall_seconds: float = 0.8
    asr_live_max_staleness_seconds: float = 1.0
    # Each live worker owns its model.  Do not invoke one native CTranslate2
    # model concurrently: that is unsafe on the supported macOS runtime.
    asr_model_workers: int = 1
    silero_threshold: float = 0.5
    audio_sample_rate: int = 16_000
    audio_debug_dir: str = ""
    asr_window_seconds: float = 0.6
    asr_overlap_seconds: float = 0.0
    asr_min_speech_seconds: float = 0.25
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
    stt_provider: str = "whisper"
    indic_conformer_model_path: str = ""
    diarization_provider: str = "demo"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
