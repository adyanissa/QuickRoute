from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.mongo import init_db
from routes.navigation_routes import router as navigation_router
from routes.auth_routes import router as auth_router
from routes.invitation_code_routes import router as invitation_code_router
from routes.building_routes import router as building_router
from routes.map_routes import router as map_router
from routes.room_routes import router as room_router
from routes.route_point_routes import router as route_point_router
from routes.route_edge_routes import router as route_edge_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="QuickRoute API",
    description="Backend API for QuickRoute indoor navigation system",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(navigation_router)
app.include_router(auth_router)
app.include_router(invitation_code_router)
app.include_router(building_router)
app.include_router(map_router)
app.include_router(room_router)
app.include_router(route_point_router)
app.include_router(route_edge_router)





@app.get("/")
def home():
    return {
        "message": "Backend is running 🚀"
    }