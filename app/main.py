from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestContextMiddleware

settings = get_settings()
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Application startup: %s", settings.app_name)
    yield
    logger.info("Application shutdown: %s", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        debug=settings.app_debug,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
        description=(
            "Reusable PDF Retrieval-Augmented Generation API with asynchronous ingestion, "
            "Qdrant retrieval, citations, conversations, and provider adapters."
        ),
    )
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.parsed_allowed_hosts,
    )
    if settings.parsed_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.parsed_cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
