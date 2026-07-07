from sqlalchemy import text


async def test_db_roundtrip(db_session):
    assert (await db_session.execute(text("select 1"))).scalar() == 1
