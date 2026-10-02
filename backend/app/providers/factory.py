from ..config import Settings
from .demo_extraction import DemoClinicalExtractionProvider
from .extraction import ClinicalExtractionProvider
from .ollama_extraction import OllamaClinicalExtractionProvider
from .speech import DemoSpeechToTextProvider, FasterWhisperProvider, SpeechToTextProvider


class LocalProviderError(RuntimeError):
    """A local model/dependency is unavailable; callers must surface the detail."""


def build_speech_provider(config: Settings | None = None) -> SpeechToTextProvider:
    selected = config or Settings()
    if selected.ai_mode == "demo":
        return DemoSpeechToTextProvider()
    if selected.ai_mode != "local":
        raise LocalProviderError(f"Unsupported AI_MODE={selected.ai_mode!r}; expected demo or local")
    if selected.stt_provider == "whisper":
        return FasterWhisperProvider(
            model_size=selected.whisper_model,
            device=selected.whisper_device,
            compute_type=selected.whisper_compute_type,
            cpu_threads=selected.asr_cpu_threads,
            num_workers=selected.asr_model_workers,
            vad_filter=selected.asr_vad_filter,
            no_speech_threshold=selected.asr_no_speech_threshold,
            log_prob_threshold=selected.asr_log_prob_threshold,
            compression_ratio_threshold=selected.asr_compression_ratio_threshold,
            min_language_probability=selected.asr_min_language_probability,
            min_avg_logprob=selected.asr_min_avg_logprob,
            max_no_speech_probability=selected.asr_max_no_speech_probability,
            max_compression_ratio=selected.asr_max_compression_ratio,
            initial_prompt=selected.asr_initial_prompt or None,
            beam_size=selected.asr_beam_size,
        )
    if selected.stt_provider == "indic_conformer":
        if not selected.indic_conformer_model_path:
            raise LocalProviderError("IndicConformer model path is missing; provision a local checkpoint and set INDIC_CONFORMER_MODEL_PATH")
        from .indic_conformer import IndicConformerProvider

        return IndicConformerProvider(model_path=selected.indic_conformer_model_path, device=selected.whisper_device)
    raise LocalProviderError(f"Unsupported STT_PROVIDER={selected.stt_provider!r}; expected whisper or indic_conformer")


def build_extraction_provider(config: Settings | None = None) -> ClinicalExtractionProvider:
    selected = config or Settings()
    if selected.ai_mode == "demo":
        return DemoClinicalExtractionProvider()
    if selected.ai_mode != "local":
        raise LocalProviderError(f"Unsupported AI_MODE={selected.ai_mode!r}; expected demo or local")
    provider = OllamaClinicalExtractionProvider(base_url=selected.ollama_base_url, model=selected.ollama_model)
    try:
        provider.check_available()
    except Exception as error:
        raise LocalProviderError(f"Local extraction unavailable: {error}") from error
    return provider
