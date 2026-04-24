import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.main import app
from app.database import get_db, Base
from app.models import Persona, PersonaSchedule

pytestmark = pytest.mark.asyncio


async def test_save_schedule_creates_and_updates(engine):
    # 准备：建一个 persona
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        db.add(Persona(slug="w", name="喝水助手", system_prompt="sys"))
        await db.commit()

    # 覆盖 get_db 依赖，让路由用测试 engine
    async def _override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            # 新增
            r = client.post(
                "/admin/detail/w/schedule",
                data={
                    "enabled": "on",
                    "prompt": "提醒用户喝水",
                    "mode": "interval",
                    "start_time": "08:00",
                    "end_time": "21:00",
                    "interval_minutes": "60",
                    "weekdays": "0,1,2,3,4,5,6",
                    "timezone": "Asia/Shanghai",
                },
                follow_redirects=False,
            )
            assert r.status_code == 303
            assert r.headers["location"] == "/admin/detail/w"

            # 再提交一次改为关闭 + 改 prompt
            r = client.post(
                "/admin/detail/w/schedule",
                data={
                    "enabled": "0",
                    "prompt": "换个提示词",
                    "mode": "interval",
                    "start_time": "09:00",
                    "end_time": "20:00",
                    "interval_minutes": "30",
                    "weekdays": "0,1,2,3,4",
                    "timezone": "Asia/Shanghai",
                },
                follow_redirects=False,
            )
            assert r.status_code == 303
    finally:
        app.dependency_overrides.clear()

    # 校验数据库
    async with Session() as db:
        from sqlalchemy import select
        result = await db.execute(select(PersonaSchedule))
        all_s = result.scalars().all()
        assert len(all_s) == 1  # 同一 persona 只有一条
        s = all_s[0]
        assert s.enabled == 0
        assert s.prompt == "换个提示词"
        assert s.start_time == "09:00"
        assert s.end_time == "20:00"
        assert s.interval_minutes == 30
        assert s.weekdays == "0,1,2,3,4"


async def test_save_schedule_404_for_missing_persona(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            r = client.post(
                "/admin/detail/nonexistent/schedule",
                data={"enabled": "1"},
                follow_redirects=False,
            )
            assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
