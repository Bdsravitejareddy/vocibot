from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine
from .api.consultations import router as consultations_router
from .api.audio import router as audio_router
from .services.runtime_status import runtime_status

app = FastAPI(title="VociBot API")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(consultations_router)
app.include_router(audio_router)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runtime-status")
def runtime_status_route() -> dict:
    return runtime_status()
