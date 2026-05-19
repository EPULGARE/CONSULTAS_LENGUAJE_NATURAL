from fastapi import FastAPI

from app.api.routes_query import router as query_router
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="Text2SQL Secure Backend", version="0.1.0")
app.include_router(query_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
