"""FastAPI entrypoint for the crypto signal agent."""

from fastapi import FastAPI

from crypto_agent.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    try:
        from crypto_agent.api.routes import router
    except ModuleNotFoundError:
        router = None

    if router is not None:
        app.include_router(router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
