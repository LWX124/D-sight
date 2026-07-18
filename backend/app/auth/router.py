import datetime as dt
import uuid

import jwt
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.deps import get_current_user
from app.auth.models import RefreshToken, User
from app.auth.schemas import LoginIn, MeOut, RegisterIn, RequestCodeIn, TokenOut
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token, create_refresh_token, decode_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "dsight_refresh"
# 轮换宽限期：旧 refresh token 被轮换后仍有效的秒数。access token 只存前端内存，
# 过期（15min）后多个并发请求 / 多标签页会各自触发一次 refresh；若旧 token 立即吊销，
# 后到的那次会拿着刚被吊销的 token → 401 → 前端 clearToken 掉线（表现为 /messages 401 风暴）。
# 给一个短宽限窗，让并发/重复刷新都能成功，且窗口足够小不削弱轮换的重放检测。
REFRESH_GRACE_S = 10


async def _issue_tokens(db: AsyncSession, user: User, response: Response) -> TokenOut:
    token, jti, expires = create_refresh_token(str(user.id))
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=expires))
    await db.commit()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=get_settings().refresh_token_ttl_days * 86400,
        path="/api/auth",
    )
    return TokenOut(access_token=create_access_token(str(user.id)))


async def _valid_refresh_row(db: AsyncSession, request: Request) -> tuple[RefreshToken, str]:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise service.AuthError(401, "缺少 refresh token")
    try:
        payload = decode_token(token, refresh=True)
    except jwt.InvalidTokenError:
        raise service.AuthError(401, "refresh token 无效")
    row = await db.get(RefreshToken, payload["jti"])
    now = dt.datetime.now(dt.UTC)
    # revoked_at 语义：<= now 才算真失效。轮换时置为未来（now+grace），故旧 token 在
    # 宽限窗内仍通过校验；logout 置为 now（<= now）即刻失效。
    revoked = row is not None and row.revoked_at is not None and row.revoked_at <= now
    if row is None or revoked or row.expires_at < now:
        raise service.AuthError(401, "refresh token 已失效，请重新登录")
    return row, payload["sub"]


@router.post("/request-code")
async def request_code(body: RequestCodeIn, db: AsyncSession = Depends(get_db)) -> Response:
    code = await service.request_code(db, body.email)
    # 测试后门：仅 FAKE_LLM 模式下回传验证码，供 E2E 无邮箱取码；生产恒为 204 无体。
    if get_settings().fake_llm:
        return JSONResponse({"debug_code": code})
    return Response(status_code=204)


@router.post("/register", status_code=201)
async def register(
    body: RegisterIn, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    user = await service.register(db, body.email, body.code, body.password)
    return await _issue_tokens(db, user, response)


@router.post("/login")
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = await service.login(db, body.email, body.password)
    return await _issue_tokens(db, user, response)


@router.post("/refresh")
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    row, sub = await _valid_refresh_row(db, request)
    # 首次轮换才设吊销时刻（now+grace）；宽限窗内的重复刷新不再延长，
    # 使旧 token 生命被固定窗口封顶，避免被反复刷新无限续命。
    if row.revoked_at is None:
        row.revoked_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=REFRESH_GRACE_S)
    user = await db.get(User, uuid.UUID(sub))
    if user is None:
        raise service.AuthError(401, "用户不存在")
    return await _issue_tokens(db, user, response)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    try:
        row, _ = await _valid_refresh_row(db, request)
        row.revoked_at = dt.datetime.now(dt.UTC)
        await db.commit()
    except service.AuthError:
        pass  # 幂等：无有效 refresh 也允许登出
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(id=str(user.id), email=user.email, role=user.role)
