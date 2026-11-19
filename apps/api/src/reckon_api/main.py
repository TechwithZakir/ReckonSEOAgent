from fastapi import FastAPI

from reckon_api.config import Settings
from reckon_api.routers.health import router as health_router


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()
    app = FastAPI(title=app_settings.app_name, version="0.1.0")
    app.include_router(health_router)
    return app


app = create_app()
