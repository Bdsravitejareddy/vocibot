from ..config import Settings
from .demo_extraction import DemoClinicalExtractionProvider
from .extraction import ClinicalExtractionProvider
from .ollama_extraction import OllamaClinicalExtractionProvider
from .speech import DemoSpeechToTextProvider, FasterWhisperProvider, MlxWhisperProvider, SpeechToTextProvider


class LocalProviderError(RuntimeError):
    """A local model/dependency is unavailable; callers must surface the detail."""


def build_speech_provider(config: Settings | None = None) -> SpeechToTextProvider:
    selected = config or Settings()
    provider = _build_whisper_provider(selected)
    if selected.ai_mode == "local" and selected.indic_asr_models_dir:
        from .indic_conformer import IndicConformerProvider, IndicRoutingProvider

        indic = IndicConformerProvider(selected.indic_asr_models_dir, threads=selected.resolved_cpu_threads)
        if indic.available():
            translator = None
            if selected.translate_to_english and selected.indic_translation_model_dir:
                from .indic_translation import IndicTranslator

                candidate = IndicTranslator(selected.indic_translation_model_dir, threads=selected.resolved_cpu_threads)
                translator = candidate if candidate.available() else None
            languages = {code.strip() for code in selected.indic_text_translation_languages.split(",") if code.strip()}
            return IndicRoutingProvider(provider, indic, translator, languages)  # type: ignore[return-value]
    return provider


def _build_whisper_provider(selected: Settings) -> SpeechToTextProvider:
    if selected.ai_mode == "demo":
        return DemoSpeechToTextProvider()
    if selected.ai_mode != "local":
        raise LocalProviderError(f"Unsupported AI_MODE={selected.ai_mode!r}; expected demo or local")
    if selected.resolved_stt_provider == "mlx_whisper":
        return MlxWhisperProvider(
            model=selected.mlx_whisper_model,
            language_id_model=selected.mlx_language_id_model,
            translation_model=selected.mlx_translation_model if selected.translate_to_english else None,
            english_check_model=selected.mlx_english_check_model,
            no_speech_threshold=selected.asr_no_speech_threshold,
            log_prob_threshold=selected.asr_log_prob_threshold,
            compression_ratio_threshold=selected.asr_compression_ratio_threshold,
            min_avg_logprob=selected.asr_min_avg_logprob,
            max_no_speech_probability=selected.asr_max_no_speech_probability,
            max_compression_ratio=selected.asr_max_compression_ratio,
            initial_prompt=selected.asr_initial_prompt or None,
        )
    if selected.resolved_stt_provider == "whisper":
        return FasterWhisperProvider(
            model_size=selected.whisper_model,
            device=selected.whisper_device,
            compute_type=selected.whisper_compute_type,
            cpu_threads=selected.resolved_cpu_threads,
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
    raise LocalProviderError(f"Unsupported STT_PROVIDER={selected.stt_provider!r}; expected auto, mlx_whisper or whisper")


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
