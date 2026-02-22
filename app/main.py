import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.logs import ApiRequestLog


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title="LoamBase API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    start = time.monotonic()
    response = await call_next(request)
    latency_ms = int((time.monotonic() - start) * 1000)

    # Best-effort logging — don't fail the request if DB write fails
    try:
        async with AsyncSessionLocal() as db:
            log = ApiRequestLog(
                timestamp=datetime.now(timezone.utc),
                method=request.method,
                endpoint=str(request.url.path),
                status_code=response.status_code,
                latency_ms=latency_ms,
                ip_address=request.client.host if request.client else None,
            )
            db.add(log)
            await db.commit()
    except Exception:
        pass

    return response


@app.get("/api/health", tags=["health"])
async def health():
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
