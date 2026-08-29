from fastapi import FastAPI
from fastapi.middleware.cors import (
    CORSMiddleware,
)

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import (
    register_exception_handlers,
)
from app.core.logging import (
    configure_logging,
)


configure_logging()


app = FastAPI(
    title=settings.app_name,
    description="Backend API for ReefCare MY",
    version="0.1.0",
)


register_exception_handlers(
    app
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        settings.cors_origin_list
    ),
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
    ],
)


@app.get("/")
async def root():
    return {
        "message": (
            "ReefCare MY backend is running"
        )
    }


app.include_router(
    api_router,
    prefix=settings.api_v1_prefix,
)