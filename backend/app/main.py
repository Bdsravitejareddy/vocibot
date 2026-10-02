from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine, migrate_sqlite_schema
from .api.consultations import router as consultations_router
from .api.audio import router as audio_router
from .api.auth import router as auth_router
from .config import settings
from .services.runtime_status import runtime_status

app = FastAPI(title="VociBot API")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_router)
app.include_router(consultations_router)
app.include_router(audio_router)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema(engine)
    from .services.recordings import start_recording_maintenance

    start_recording_maintenance()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runtime-status")
def runtime_status_route() -> dict:
    return runtime_status()
