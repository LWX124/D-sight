import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import require_admin
from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import get_db
from app.social.models import WeiboAccount, WeiboCredential, WeiboPost, WeiboSubscription
from app.social.weibo import cooldown
from app.social.weibo.credentials import (
    disable_credential,
    mark_blocked,
    mark_expired,
    pick_credential,
    replace_credential,
)
from app.social.weibo.errors import (
    InvalidWeiboPayloadError,
    InvalidWeiboProfileUrlError,
    WeiboRateLimitedError,
    WeiboSessionExpiredError,
    WeiboTransientError,
)
from app.social.weibo.ingest import (
    ingest_account,
    mark_account_error,
    parse_profile_uid,
    preview_account,
)
from app.social.weibo.schemas import (
    AccountOut,
    CredentialIn,
    CredentialStatusOut,
    PostOut,
    PreviewIn,
    SubscribeResult,
    SubscriptionIn,
    SubscriptionOut,
)

router = APIRouter(prefix="/weibo", tags=["social-weibo"])


def _rate_http(seconds: int) -> HTTPException:
    retry = max(1, seconds)
    return HTTPException(
        429,
        f"微博接口处于风控冷却中，请约 {(retry + 59) // 60} 分钟后重试",
        headers={"Retry-After": str(retry)},
    )


def _subscription_out(sub: WeiboSubscription, account: WeiboAccount) -> SubscriptionOut:
    return SubscriptionOut(
        id=str(sub.id),
        account_id=str(account.id),
        uid=account.uid,
        name=account.name,
        avatar=account.avatar,
        description=account.description,
        profile_url=account.profile_url,
        enabled=sub.enabled,
        last_synced_at=account.last_synced_at,
        last_sync_status=account.last_sync_status,
        last_sync_error=account.last_sync_error,
    )


async def _active_or_409(db: AsyncSession):
    credential = await pick_credential(db)
    if credential is None:
        raise HTTPException(409, "微博 Cookie 未配置或已失效，请联系管理员重新配置")
    return credential


async def _handle_upstream(db: AsyncSession, exc: Exception) -> HTTPException:
    credential = await pick_credential(db)
    if isinstance(exc, WeiboSessionExpiredError):
        if credential is not None:
            await mark_expired(db, credential.id)
        return HTTPException(409, "微博登录已过期，请联系管理员重新配置 Cookie")
    if isinstance(exc, WeiboRateLimitedError):
        seconds = get_settings().weibo_global_cooldown_minutes * 60
        await cooldown.trip(seconds)
        if credential is not None:
            await mark_blocked(db, credential.id, seconds, str(exc))
        return _rate_http(seconds)
    if isinstance(exc, (WeiboTransientError, InvalidWeiboPayloadError)):
        return HTTPException(503, f"微博内容暂时获取失败：{exc}")
    raise exc


@router.get("/credential", response_model=CredentialStatusOut)
async def credential_status(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CredentialStatusOut:
    row = await db.scalar(
        select(WeiboCredential).order_by(WeiboCredential.created_at.desc()).limit(1)
    )
    return CredentialStatusOut(
        configured=row is not None,
        status=row.status if row else None,
        weibo_uid=row.weibo_uid if row else None,
        nickname=row.nickname if row else None,
        avatar=row.avatar if row else None,
        last_verified_at=row.last_verified_at if row else None,
        blocked_until=row.blocked_until if row else None,
        last_error=row.last_error if row else None,
        can_manage=user.role == "admin",
    )


@router.put("/credential", response_model=CredentialStatusOut)
async def put_credential(
    body: CredentialIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CredentialStatusOut:
    try:
        row = await replace_credential(db, admin.id, body.cookies)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except WeiboSessionExpiredError as exc:
        raise HTTPException(409, "提供的微博 Cookie 已失效") from exc
    except WeiboRateLimitedError as exc:
        seconds = get_settings().weibo_global_cooldown_minutes * 60
        await cooldown.trip(seconds)
        active = await pick_credential(db)
        if active is not None:
            await mark_blocked(db, active.id, seconds, str(exc))
        raise _rate_http(seconds) from exc
    except (WeiboTransientError, InvalidWeiboPayloadError) as exc:
        raise HTTPException(503, f"微博 Cookie 验证失败：{exc}") from exc
    await cooldown.clear()
    return CredentialStatusOut(
        configured=True,
        status=row.status,
        weibo_uid=row.weibo_uid,
        nickname=row.nickname,
        avatar=row.avatar,
        last_verified_at=row.last_verified_at,
        blocked_until=None,
        last_error=None,
        can_manage=True,
    )


@router.delete("/credential")
async def delete_credential(
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    del admin
    await disable_credential(db)
    await cooldown.clear()
    return {"ok": True}


@router.post("/accounts/preview", response_model=AccountOut)
async def preview(
    body: PreviewIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountOut:
    del user
    try:
        parse_profile_uid(body.profile_url)
    except InvalidWeiboProfileUrlError as exc:
        raise HTTPException(422, str(exc)) from exc
    left = await cooldown.remaining()
    if left:
        raise _rate_http(left)
    await _active_or_409(db)
    try:
        account = await preview_account(db, body.profile_url)
    except (
        WeiboSessionExpiredError,
        WeiboRateLimitedError,
        WeiboTransientError,
        InvalidWeiboPayloadError,
    ) as exc:
        raise await _handle_upstream(db, exc)
    return AccountOut(
        account_id=str(account.id),
        uid=account.uid,
        name=account.name,
        avatar=account.avatar,
        description=account.description,
        profile_url=account.profile_url,
    )


@router.post("/subscriptions", response_model=SubscribeResult)
async def subscribe(
    body: SubscriptionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscribeResult:
    try:
        account_id = uuid.UUID(body.account_id)
    except ValueError as exc:
        raise HTTPException(422, "account_id 格式无效") from exc
    account = await db.get(WeiboAccount, account_id)
    if account is None:
        raise HTTPException(404, "微博账号不存在，请先预览确认")

    # 串行化账号上限检查，防止两个用户同时订阅新 UID 越过全实例上限。
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 867426})
    sub = await db.scalar(
        select(WeiboSubscription).where(
            WeiboSubscription.user_id == user.id,
            WeiboSubscription.account_id == account.id,
        )
    )
    is_new_account = (
        await db.scalar(
            select(WeiboSubscription.id)
            .where(
                WeiboSubscription.account_id == account.id,
                WeiboSubscription.enabled.is_(True),
            )
            .limit(1)
        )
        is None
    )
    if is_new_account:
        active_accounts = await db.scalar(
            select(func.count(distinct(WeiboSubscription.account_id))).where(
                WeiboSubscription.enabled.is_(True)
            )
        )
        if (active_accounts or 0) >= get_settings().weibo_max_accounts:
            raise HTTPException(409, "当前实例最多同时订阅 20 个微博账号")
    created = sub is None
    if sub is None:
        sub = WeiboSubscription(user_id=user.id, account_id=account.id, enabled=True)
        db.add(sub)
    else:
        sub.enabled = True
    # Keep the new subscription and its initial snapshots in one transaction.
    # ingest_account commits on success; on an upstream failure mark_account_error
    # rolls this transaction back before persisting only the account error state.
    # Committing here would leave a subscription behind after a 409/429/503, and
    # the idempotent retry would then skip the initial sync forever.
    await db.flush()

    added = 0
    sync_status = "already_subscribed"
    if created:
        left = await cooldown.remaining()
        if left:
            sync_status = "cooldown"
            await db.commit()
        else:
            credential = await _active_or_409(db)
            try:
                added = await ingest_account(db, account, credential, initial=True)
                sync_status = "ok"
            except (
                WeiboSessionExpiredError,
                WeiboRateLimitedError,
                WeiboTransientError,
                InvalidWeiboPayloadError,
            ) as exc:
                await mark_account_error(db, account.id, str(exc))
                raise await _handle_upstream(db, exc)
    else:
        await db.commit()
    await db.refresh(sub)
    return SubscribeResult(
        subscription=_subscription_out(sub, account),
        initial_sync_status=sync_status,
        added=added,
    )


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[SubscriptionOut]:
    rows = (
        await db.execute(
            select(WeiboSubscription, WeiboAccount)
            .join(WeiboAccount, WeiboSubscription.account_id == WeiboAccount.id)
            .where(
                WeiboSubscription.user_id == user.id,
                WeiboSubscription.enabled.is_(True),
            )
            .order_by(WeiboSubscription.created_at.desc())
        )
    ).all()
    return [_subscription_out(sub, account) for sub, account in rows]


@router.delete("/subscriptions/{subscription_id}")
async def unsubscribe(
    subscription_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sub = await db.get(WeiboSubscription, subscription_id)
    if sub is None or sub.user_id != user.id:
        raise HTTPException(404, "微博订阅不存在")
    await db.delete(sub)
    await db.commit()
    return {"ok": True}


@router.get("/posts", response_model=list[PostOut])
async def list_posts(
    account_id: uuid.UUID,
    before: dt.datetime | None = None,
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PostOut]:
    allowed = await db.scalar(
        select(WeiboSubscription.id).where(
            WeiboSubscription.user_id == user.id,
            WeiboSubscription.account_id == account_id,
            WeiboSubscription.enabled.is_(True),
        )
    )
    if allowed is None:
        raise HTTPException(403, "无权读取该微博账号内容")
    query = (
        select(WeiboPost, WeiboAccount.name)
        .join(WeiboAccount, WeiboPost.account_id == WeiboAccount.id)
        .where(WeiboPost.account_id == account_id)
    )
    if before is not None:
        query = query.where(WeiboPost.published_at < before)
    rows = (await db.execute(query.order_by(WeiboPost.published_at.desc()).limit(limit))).all()
    return [
        PostOut(
            id=str(post.id),
            account_id=str(post.account_id),
            account_name=name,
            external_id=post.external_id,
            content=post.content,
            url=post.url,
            media=post.media,
            published_at=post.published_at,
            captured_at=post.captured_at,
        )
        for post, name in rows
    ]


@router.post("/refresh")
async def refresh(
    account_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sub = await db.scalar(
        select(WeiboSubscription).where(
            WeiboSubscription.user_id == user.id,
            WeiboSubscription.account_id == account_id,
            WeiboSubscription.enabled.is_(True),
        )
    )
    if sub is None:
        raise HTTPException(403, "只能刷新自己订阅的微博账号")
    left = await cooldown.remaining()
    if left:
        raise _rate_http(left)
    credential = await _active_or_409(db)
    wait = await cooldown.try_acquire_refresh(
        str(account_id), get_settings().weibo_refresh_cooldown_seconds
    )
    if wait:
        raise HTTPException(
            429,
            f"该微博账号刚刷新过，请 {wait} 秒后再试",
            headers={"Retry-After": str(wait)},
        )
    account = await db.get(WeiboAccount, account_id)
    try:
        added = await ingest_account(db, account, credential)
    except (
        WeiboSessionExpiredError,
        WeiboRateLimitedError,
        WeiboTransientError,
        InvalidWeiboPayloadError,
    ) as exc:
        await mark_account_error(db, account_id, str(exc))
        if not isinstance(exc, WeiboRateLimitedError):
            await cooldown.release_refresh(str(account_id))
        raise await _handle_upstream(db, exc)
    return {"added": added}
