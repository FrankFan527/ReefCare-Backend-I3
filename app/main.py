from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    description="Backend API for ReefCare MY",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {
        "message": "ReefCare MY backend is running"
    }


app.include_router(
    api_router,
    prefix=settings.api_v1_prefix,
)