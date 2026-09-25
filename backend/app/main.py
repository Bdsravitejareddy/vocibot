from fastapi import FastAPI

from .db import Base, engine

app = FastAPI(title="VociBot API")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
