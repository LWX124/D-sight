from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="D-sight API")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
