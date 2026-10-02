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
    from .services.processing import resume_unfinished
    from .services.recordings import start_recording_maintenance

    start_recording_maintenance()
    resume_unfinished()


def mount_web_app() -> None:
    """Serve the exported UI after every API route, when configured."""

    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    root = Path(settings.web_root).expanduser() if settings.web_root else None
    if root is not None and (root / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(root), html=True), name="web")


@app.get("/ca.crt", include_in_schema=False)
def ca_certificate():
    """The clinic's local CA certificate, for doctors' devices to trust (public, no secrets)."""

    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    path = Path(settings.ca_cert_path) if settings.ca_cert_path else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="This server does not use a local certificate authority.")
    return FileResponse(path, media_type="application/x-x509-ca-cert", filename="vocibot-clinic-ca.crt")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runtime-status")
def runtime_status_route() -> dict:
    return runtime_status()


mount_web_app()
