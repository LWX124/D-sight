from sqlalchemy.dialects.postgresql import JSONB

from app.social.models import WeiboAccount, WeiboCredential, WeiboPost, WeiboSubscription


def test_weibo_model_contracts_are_non_nullable_and_unique():
    assert WeiboCredential.__table__.c.cookies.nullable is False
    assert WeiboAccount.__table__.c.uid.nullable is False
    assert WeiboPost.__table__.c.content.nullable is False
    assert WeiboPost.__table__.c.published_at.nullable is False
    assert isinstance(WeiboPost.__table__.c.media.type, JSONB)
    post_constraints = {constraint.name for constraint in WeiboPost.__table__.constraints}
    subscription_constraints = {
        constraint.name for constraint in WeiboSubscription.__table__.constraints
    }
    assert "uq_weibo_account_external" in post_constraints
    assert "uq_weibo_sub_user_account" in subscription_constraints
