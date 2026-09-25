from fastapi import FastAPI

from .db import Base, engine
from .api.consultations import router as consultations_router

app = FastAPI(title="VociBot API")
app.include_router(consultations_router)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
