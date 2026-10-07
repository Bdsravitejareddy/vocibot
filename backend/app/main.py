import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine, migrate_sqlite_schema
from .api.consultations import router as consultations_router
from .api.audio import router as audio_router
from .api.settings import router as settings_router
from .api.voice_profiles import router as voice_profiles_router
from .api.learning import router as learning_router
from .services.runtime_status import runtime_status

app = FastAPI(title="VociBot API")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:3001", "http://localhost:3001"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(consultations_router)
app.include_router(audio_router)
app.include_router(settings_router)
app.include_router(voice_profiles_router)
app.include_router(learning_router)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema(engine)
    from .services.recordings import start_recording_maintenance

    start_recording_maintenance()
    from .learning.scheduler import start_scheduler

    start_scheduler()
    threading.Thread(target=_warm_language_models, name="warm-language-models", daemon=True).start()


def _warm_language_models() -> None:
    """Non-English consultations need the translation and English-check
    models; load them in the background at start, not in the first one."""

    import logging

    from .config import settings
    from .db import SessionLocal
    from .languages import enabled_languages

    try:
        with SessionLocal() as session:
            if settings.ai_mode != "local" or set(enabled_languages(session)) <= {"en"}:
                return
        from .providers.factory import build_speech_provider

        provider = build_speech_provider(settings)
        whisper = getattr(provider, "whisper", provider)
        if hasattr(whisper, "warmup_languages"):
            whisper.warmup_languages()
    except Exception:
        logging.getLogger(__name__).exception("Warming the language models failed; they load on first use instead")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runtime-status")
def runtime_status_route() -> dict:
    return runtime_status()
