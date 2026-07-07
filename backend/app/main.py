from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.auth.service import AuthError


def create_app() -> FastAPI:
    app = FastAPI(title="D-sight API")

    @app.exception_handler(AuthError)
    async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    app.include_router(auth_router)
    return app
