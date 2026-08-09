import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from logging.config import dictConfig

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database.mongo import init_db
from routes.auth_routes import router as auth_router
from routes.building_routes import router as building_router
from routes.invitation_code_routes import (
    router as invitation_code_router,
)
from routes.location_code_routes import (
    router as location_code_router,
)
from routes.maintenance_routes import (
    router as maintenance_router,
)
from routes.map_groups_routes import (
    router as map_groups_router,
)
from routes.map_routes import router as map_router
from routes.navigation_cleanup_routes import (
    router as navigation_cleanup_router,
)
from routes.navigation_routes import (
    router as navigation_router,
)
from routes.room_routes import router as room_router
from routes.route_edge_routes import (
    router as route_edge_router,
)
from routes.route_point_routes import (
    router as route_point_router,
)
from routes.semantic_analysis_routes import (
    router as semantic_analysis_router,
)
from routes.vertical_connectors_routes import (
    router as vertical_connectors_router,
)
from services.map_image_service import (
    UPLOADS_DIR,
    ensure_map_directories,
)
from services.semantic_analysis_worker import (
    worker as semantic_analysis_worker,
)


# ------------------------------------------------------------------
# Central logging configuration
# Logs are written to stdout so AWS can collect them in CloudWatch.
# ------------------------------------------------------------------

dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": (
                    "%(asctime)s | %(levelname)s | "
                    "%(name)s | %(message)s"
                ),
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["console"],
        },
    }
)

logger = logging.getLogger("quickroute.app")


# Create uploads/maps folders before StaticFiles is mounted.
ensure_map_directories()


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_started = False

    logger.info("application_starting")

    try:
        await init_db()
        logger.info(
            "database_initialized database=quickroute_db"
        )

        semantic_analysis_worker.start()
        worker_started = True

        logger.info("semantic_analysis_worker_started")
        logger.info("application_started")

        yield

    except Exception:
        logger.exception("application_lifecycle_failed")
        raise

    finally:
        if worker_started:
            try:
                await semantic_analysis_worker.stop()
                logger.info(
                    "semantic_analysis_worker_stopped"
                )
            except Exception:
                logger.exception(
                    "semantic_analysis_worker_stop_failed"
                )

        logger.info("application_stopped")


app = FastAPI(
    title="QuickRoute API",
    description=(
        "Backend API for QuickRoute "
        "indoor navigation system"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ------------------------------------------------------------------
# CORS configuration
#
# Local development uses the localhost origins below by default.
# Production can override them through CORS_ALLOWED_ORIGINS.
#
# Example:
# CORS_ALLOWED_ORIGINS=https://dy18iemulrjcj.cloudfront.net
#
# Multiple origins must be separated by commas.
# ------------------------------------------------------------------

default_cors_origins = (
    "http://localhost:5173,"
    "http://127.0.0.1:5173,"
    "http://localhost:5174,"
    "http://127.0.0.1:5174"
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        default_cors_origins,
    ).split(",")
    if origin.strip()
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# HTTP request logging middleware
# ------------------------------------------------------------------

@app.middleware("http")
async def log_http_requests(
    request: Request,
    call_next,
):
    request_id = (
        request.headers.get("X-Request-ID")
        or str(uuid.uuid4())
    )

    start_time = time.perf_counter()

    try:
        response = await call_next(request)

        duration_ms = (
            time.perf_counter() - start_time
        ) * 1000

        log_details = (
            "request_completed "
            "request_id=%s "
            "method=%s "
            "path=%s "
            "status=%s "
            "duration_ms=%.2f"
        )

        if response.status_code >= 500:
            logger.error(
                log_details,
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        elif response.status_code >= 400:
            logger.warning(
                log_details,
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        else:
            logger.info(
                log_details,
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )

        response.headers["X-Request-ID"] = request_id
        return response

    except Exception:
        duration_ms = (
            time.perf_counter() - start_time
        ) * 1000

        logger.exception(
            "request_failed "
            "request_id=%s "
            "method=%s "
            "path=%s "
            "duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            duration_ms,
        )

        raise


# Makes generated map files available through:
# http://127.0.0.1:8000/uploads/...
app.mount(
    "/uploads",
    StaticFiles(
        directory=str(UPLOADS_DIR)
    ),
    name="uploads",
)


app.include_router(navigation_router)
app.include_router(auth_router)
app.include_router(invitation_code_router)
app.include_router(building_router)
app.include_router(map_router)
app.include_router(navigation_cleanup_router)
app.include_router(map_groups_router)
app.include_router(room_router)
app.include_router(route_point_router)
app.include_router(route_edge_router)
app.include_router(location_code_router)
app.include_router(maintenance_router)
app.include_router(vertical_connectors_router)
app.include_router(semantic_analysis_router)


@app.get("/")
def home():
    return {
        "message": "Backend is running 🚀"
    }