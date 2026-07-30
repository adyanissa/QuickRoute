from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database.mongo import init_db
from routes.auth_routes import router as auth_router
from routes.building_routes import router as building_router
from routes.invitation_code_routes import (
    router as invitation_code_router,
)
from routes.map_routes import router as map_router
from routes.map_groups_routes import (
    router as map_groups_router,
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
from routes.location_code_routes import (
    router as location_code_router,
)
from routes.maintenance_routes import (
    router as maintenance_router,
)
from routes.vertical_connectors_routes import (
    router as vertical_connectors_router,
)
from routes.semantic_analysis_routes import (
    router as semantic_analysis_router,
)
from services.map_image_service import (
    UPLOADS_DIR,
    ensure_map_directories,
)
from services.semantic_analysis_worker import worker as semantic_analysis_worker


# Create uploads/maps folders before StaticFiles is mounted.
ensure_map_directories()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Persistent, MongoDB-backed semantic-analysis worker (Section 10).
    # Started only after Beanie/the DB connection is ready; stopped
    # cleanly on shutdown so no AI-provider call is left running
    # mid-request when the process exits.
    semantic_analysis_worker.start()
    try:
        yield
    finally:
        await semantic_analysis_worker.stop()


app = FastAPI(
    title="QuickRoute API",
    description=(
        "Backend API for QuickRoute "
        "indoor navigation system"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Primary Vite dev server port.
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # Vite's automatic fallback port: if 5173 is still held by a
        # process from a previous session (e.g. after the machine sleeps
        # and dev servers are restarted without the old one fully
        # exiting), Vite silently starts on 5174 instead. Without this,
        # the browser's login/API requests fail the CORS preflight and
        # surface as a generic "Failed to fetch" with no HTTP status —
        # not an auth error — even though the backend itself is up.
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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