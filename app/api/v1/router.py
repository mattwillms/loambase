from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, gardens, journal, plants, plantings, recommendations, schedules, soil, treatments, weather, zones

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(gardens.router)
api_router.include_router(gardens.beds_router)
api_router.include_router(plants.router)
api_router.include_router(plantings.router)
api_router.include_router(schedules.router)
api_router.include_router(schedules.watering_groups_router)
api_router.include_router(schedules.planting_assignment_router)
api_router.include_router(treatments.router)
api_router.include_router(treatments.watering_router)
api_router.include_router(recommendations.router)
api_router.include_router(weather.router)
api_router.include_router(soil.router)
api_router.include_router(zones.router)
api_router.include_router(journal.router)
api_router.include_router(admin.router)
