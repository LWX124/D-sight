import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.aihot.enrichment import ENRICHMENT_VERSION
from app.aihot.models import (
    ContentEnrichment,
    HotItemSource,
    HotRanking,
    HotRun,
    HotSourceMembership,
)
from app.aihot.ranking import FORMULA_VERSION
from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.social.unified_models import (
    SocialItem,
    SocialItemMetricSnapshot,
    SocialPublisher,
)


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _user(db_session, role="user") -> User:
    user = User(
        email=f"aihot-{uuid.uuid4()}@test.dev",
        password_hash=hash_password("pw-12345"),
        role=role,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_aihot_management_requires_admin(client, db_session):
    user = await _user(db_session)
    headers = _auth(user)
    assert (await client.get("/api/aihot/sources", headers=headers)).status_code == 403
    assert (await client.post("/api/aihot/refresh", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_xiaohongshu_keyword_source_without_fake_publisher(
    client, db_session
):
    admin = await _user(db_session, role="admin")
    response = await client.post(
        "/api/aihot/sources",
        headers=_auth(admin),
        json={
            "platform": "xiaohongshu",
            "source_key": "金融政策",
            "category": "policy",
        },
    )
    assert response.status_code == 201
    sources = (await client.get("/api/aihot/sources", headers=_auth(admin))).json()
    source = next(row for row in sources if row["id"] == response.json()["id"])
    assert source["publisher_id"] is None
    assert source["platform"] == "xiaohongshu"
    assert source["source_key"] == "金融政策"


@pytest.mark.asyncio
async def test_admin_can_create_redfox_account_source_without_publisher_uuid(
    client, db_session
):
    admin = await _user(db_session, role="admin")
    external_id = f"account-{uuid.uuid4()}"
    payload = {
        "platform": "wechat",
        "external_id": external_id,
        "name": "服务端创建的公众号",
        "avatar": "https://example.test/avatar.png",
        "description": "长期金融研究",
        "category": "company",
    }
    response = await client.post(
        "/api/aihot/sources",
        headers=_auth(admin),
        json=payload,
    )
    assert response.status_code == 201
    publisher = await db_session.scalar(
        select(SocialPublisher).where(
            SocialPublisher.platform == "wechat",
            SocialPublisher.external_id == external_id,
        )
    )
    membership = await db_session.get(
        HotSourceMembership,
        uuid.UUID(response.json()["id"]),
    )
    assert publisher is not None
    assert publisher.provider == "redfox"
    assert publisher.description == "长期金融研究"
    assert membership.publisher_id == publisher.id
    assert membership.category == "company"

    duplicate = await client.post(
        "/api/aihot/sources",
        headers=_auth(admin),
        json=payload,
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_admin_can_still_create_source_with_publisher_id(client, db_session):
    admin = await _user(db_session, role="admin")
    publisher = SocialPublisher(
        platform="bilibili",
        external_id=f"legacy-source-{uuid.uuid4()}",
        name="既有 B 站账号",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add(publisher)
    await db_session.commit()

    response = await client.post(
        "/api/aihot/sources",
        headers=_auth(admin),
        json={"publisher_id": str(publisher.id), "category": "market"},
    )

    assert response.status_code == 201
    membership = await db_session.get(
        HotSourceMembership,
        uuid.UUID(response.json()["id"]),
    )
    assert membership is not None
    assert membership.publisher_id == publisher.id

    invalid = await client.post(
        "/api/aihot/sources",
        headers=_auth(admin),
        json={
            "publisher_id": str(publisher.id),
            "source_key": "账号源不能附带关键词",
        },
    )
    assert invalid.status_code == 422

    invalid_patch = await client.patch(
        f"/api/aihot/sources/{membership.id}",
        headers=_auth(admin),
        json={"source_key": "账号源不能改成关键词源"},
    )
    assert invalid_patch.status_code == 422

    null_patch = await client.patch(
        f"/api/aihot/sources/{membership.id}",
        headers=_auth(admin),
        json={"enabled": None},
    )
    assert null_patch.status_code == 422


@pytest.mark.asyncio
async def test_xiaohongshu_account_source_is_rejected(client, db_session):
    admin = await _user(db_session, role="admin")
    response = await client.post(
        "/api/aihot/sources",
        headers=_auth(admin),
        json={
            "platform": "xiaohongshu",
            "external_id": f"xhs-{uuid.uuid4()}",
            "name": "不支持的账号源",
        },
    )
    assert response.status_code == 422
    assert "关键词" in response.json()["detail"]


@pytest.mark.asyncio
async def test_bookmark_cannot_turn_private_content_into_visible_content(client, db_session):
    user = await _user(db_session)
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"private-{uuid.uuid4()}",
        name="他人的订阅",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add(publisher)
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"private-item-{uuid.uuid4()}",
        content_type="article",
        title="不可见内容",
        published_at=datetime.now(timezone.utc),
        platform_metadata={},
    )
    db_session.add(item)
    await db_session.commit()
    response = await client.post(
        "/api/social/bookmarks",
        headers=_auth(user),
        json={"item_id": str(item.id)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_aihot_list_returns_saved_card_contract_without_total_score(client, db_session):
    user = await _user(db_session)
    now = datetime.now(timezone.utc)
    publisher = SocialPublisher(
        platform="bilibili",
        external_id=f"mid-{uuid.uuid4()}",
        name="金融作者",
        provider="redfox",
        platform_metadata={},
    )
    db_session.add(publisher)
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="bilibili",
        external_id=f"bv-{uuid.uuid4()}",
        content_type="video",
        title="利率政策影响市场",
        digest="原始摘要",
        url="https://example.test/video",
        published_at=now,
        platform_metadata={},
    )
    source = HotSourceMembership(
        publisher_id=publisher.id,
        platform="bilibili",
        category="policy",
        added_by=user.id,
    )
    run = HotRun(
        platform="all",
        provider="redfox",
        run_type="scheduled",
        status="success",
        started_at=now,
        finished_at=now,
        formula_version=FORMULA_VERSION,
        items_fetched=1,
    )
    db_session.add_all([item, source, run])
    await db_session.flush()
    db_session.add_all(
        [
            HotItemSource(item_id=item.id, source_id=source.id),
            SocialItemMetricSnapshot(
                item_id=item.id,
                captured_at=now,
                view_count=12345,
                raw_metrics={},
            ),
            ContentEnrichment(
                item_id=item.id,
                model="fake",
                version=ENRICHMENT_VERSION,
                is_financial=True,
                relevance_confidence=0.99,
                summary="AI 摘要",
                category="policy",
                assets=["沪深300"],
                status="done",
                generated_at=now,
            ),
            HotRanking(
                run_id=run.id,
                item_id=item.id,
                platform="bilibili",
                category="policy",
                window="24h",
                aihot_score=88,
                rank=1,
                previous_rank=3,
                rank_delta=2,
                platform_score=100,
                freshness_score=100,
                momentum_score=60,
                formula_version=FORMULA_VERSION,
                computed_at=now,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/aihot?window=24h", headers=_auth(user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    card = payload["items"][0]
    assert card["id"] == str(item.id)
    assert card["rank_delta"] == 2 and card["trend"] == "up"
    assert card["digest"] == "AI 摘要"
    assert card["assets"] == ["沪深300"]
    assert card["core_metric"] == {"label": "播放", "value": 12345}
    assert "aihot_score" not in card
    bookmark = await client.post(
        "/api/social/bookmarks", headers=_auth(user), json={"item_id": str(item.id)}
    )
    assert bookmark.status_code == 200
