from ..config import Settings
from .demo_extraction import DemoClinicalExtractionProvider
from .extraction import ClinicalExtractionProvider
from .ollama_extraction import OllamaClinicalExtractionProvider


class LocalProviderError(RuntimeError):
    """A local model/dependency is unavailable; callers must surface the detail."""


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
