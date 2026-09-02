"""FastAPI application entry point."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.init_db import initialise
from app.db.session import engine
from app.services.ingest import IngestError
from app.services.query_engine import QueryError
from app.services.survey_solutions import SurveySolutionsError

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s %s (%s)", settings.project_name, __version__, settings.environment)
    for attempt in range(1, 31):
        try:
            initialise()
            break
        except SQLAlchemyError as exc:
            # Postgres may still be accepting connections when the API starts
            logger.warning("Database not ready (attempt %s/30): %s", attempt, exc)
            time.sleep(2)
    else:
        logger.error("Could not reach the database; starting in a degraded state")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.project_name,
    version=__version__,
    description=(
        "Survey data monitoring platform: connect to Survey Solutions, import Stata "
        "and other survey files, tabulate, chart and monitor field work."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_timing_header(request: Request, call_next):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


@app.exception_handler(QueryError)
async def handle_query_error(request: Request, exc: QueryError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(IngestError)
async def handle_ingest_error(request: Request, exc: IngestError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(SurveySolutionsError)
async def handle_suso_error(request: Request, exc: SurveySolutionsError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return validation problems in a shape the UI can show next to fields."""
    errors = [
        {
            "field": ".".join(str(part) for part in error["loc"][1:]) or "body",
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": errors[0]["message"] if errors else "Invalid request", "errors": errors},
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["system"])
def health() -> dict[str, object]:
    """Liveness and readiness probe used by Docker and load balancers."""
    database_ok = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_ok = False
    return {
        "status": "ok" if database_ok else "degraded",
        "version": __version__,
        "database": "ok" if database_ok else "unreachable",
    }
