from fastapi import APIRouter

from app.api.v1.endpoints import auth, gardens, plants, plantings, weather, zones

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(gardens.router)
api_router.include_router(gardens.beds_router)
api_router.include_router(plants.router)
api_router.include_router(plantings.router)
api_router.include_router(weather.router)
api_router.include_router(zones.router)
