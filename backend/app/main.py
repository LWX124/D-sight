from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.admin.router import router as admin_router
from app.agent.build import make_checkpointer
from app.auth.router import router as auth_router
from app.auth.service import AuthError
from app.chat.router import router as chat_router
from app.core.config import get_settings
from app.credits.router import router as credits_router
from app.kb.router import router as kb_router
from app.news.router import router as news_router
from app.skills.router import router as skills_router
from app.social.router import router as social_router
from app.threads.router import router as threads_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """进程级持有一个 AsyncPostgresSaver（checkpointer）。

    ASGITransport 测试不跑 lifespan，故 ``app.state.checkpointer`` 缺省 → 端点走
    None 分支（build_agent 用 deepagents 默认内存 checkpointer）。
    """
    from app.core.scheduler import start_scheduler, stop_scheduler
    from app.social.crypto import assert_prod_key_configured

    cm = make_checkpointer(get_settings().database_url)
    async with cm as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        assert_prod_key_configured()
        start_scheduler()
        try:
            yield
        finally:
            stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(title="D-sight API", lifespan=lifespan)

    @app.exception_handler(AuthError)
    async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(threads_router)
    app.include_router(chat_router)
    app.include_router(admin_router)
    app.include_router(credits_router)
    app.include_router(skills_router)
    app.include_router(kb_router)
    app.include_router(news_router)
    app.include_router(social_router)
    return app
