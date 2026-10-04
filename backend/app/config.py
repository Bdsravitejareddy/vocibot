from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ai_mode: str = "demo"
    database_url: str = "sqlite:///./vocibot.db"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    # A cold 8B model plus a long consultation can take well over 30 s locally.
    ollama_timeout_seconds: float = 120.0
    # Upper bound for the per-consultation context (a 30-minute consultation
    # needs ~10k tokens); the context is otherwise sized to each prompt.
    ollama_max_context: int = 12288
    # How long the note model stays loaded after a note.
    ollama_keep_alive: str = "30m"
    # GPU layers for the note model: -1 lets Ollama decide, 0 forces CPU.
    ollama_num_gpu: int = -1
    # CPU threads for the note model (0 = Ollama default).
    ollama_num_thread: int = 0
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    # CPU models (IndicConformer, IndicTrans2, voice fingerprints) use this many
    # threads; 0 = the performance cores (10 on an M4 Pro).
    asr_cpu_threads: int = 0
    # Live preview re-transcribes the unsettled audio buffer every step.  A
    # segment is settled once a later one follows it or `holdback` seconds of
    # audio have passed after it; the buffer is force-settled at `max_buffer`.
    asr_live_step_seconds: float = 0.35
    asr_live_holdback_seconds: float = 1.2
    asr_live_max_buffer_seconds: float = 8.0
    # Includes the English translation of non-English consultations.
    asr_finalization_timeout_seconds: float = 180.0
    # Each live worker owns its model.  Do not invoke one native CTranslate2
    # model concurrently: that is unsafe on the supported macOS runtime.
    asr_model_workers: int = 1
    silero_threshold: float = 0.5
    audio_sample_rate: int = 16_000
    audio_debug_dir: str = ""
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
    # Language identification and English translation need the full model:
    # turbo identifies Telugu 0% of the time and was not trained to translate.
    mlx_language_id_model: str = "mlx-community/whisper-large-v3-mlx"
    mlx_translation_model: str = "mlx-community/whisper-large-v3-mlx"
    # "Is this line English?" in Indian-language consultations: as accurate as
    # large-v3 on the clinic's code-mixed test and dataset clips, 6x faster
    # (0.1 s per line).
    mlx_english_check_model: str = "mlx-community/whisper-small-mlx"
    # Non-English consultations get an English translation (from the audio)
    # that the clinical note is written from.
    translate_to_english: bool = True
    # Folder of exported IndicConformer models (<lang>/model.onnx, vocab.json,
    # features.npz): used for the final transcript of those languages.
    indic_asr_models_dir: str = ""
    # IndicTrans2 CTranslate2 model folder, and the languages whose
    # IndicConformer text it translates (others: Whisper from the audio).
    indic_translation_model_dir: str = ""
    indic_text_translation_languages: str = "hi"
    # Label transcript lines doctor/patient from their content before the note.
    speaker_roles_enabled: bool = True
    # SpeechBrain ECAPA speaker model folder (embedding_model.ckpt): doctor voice profiles.
    voice_model_dir: str = ""
    diarization_provider: str = "demo"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def resolved_cpu_threads(self) -> int:
        """asr_cpu_threads, or the performance cores (efficiency cores are slower
        and would hold back every thread of a parallel computation)."""

        if self.asr_cpu_threads > 0:
            return self.asr_cpu_threads
        import os
        import subprocess

        try:
            return max(1, int(subprocess.run(["sysctl", "-n", "hw.perflevel0.physicalcpu"], capture_output=True, text=True, timeout=2).stdout.strip()))
        except (OSError, ValueError, subprocess.SubprocessError):
            return max(1, (os.cpu_count() or 4) - 2)

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
