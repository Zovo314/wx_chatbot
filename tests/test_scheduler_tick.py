"""验证 _tick 扫描 schedule 并对命中的触发 generate+broadcast。"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Persona, PersonaSchedule

pytestmark = pytest.mark.asyncio


async def test_tick_fires_matching_schedule(db, monkeypatch, engine):
    from app.services import scheduler as sch

    p = Persona(slug="w", name="W", system_prompt="sys",
                meta_json='{"kf":{"open_kfid":"kf1"}}')
    db.add(p)
    await db.flush()

    s = PersonaSchedule(
        persona_id=p.id, enabled=1, prompt="测试提示词",
        mode="interval", start_time="00:00", end_time="23:59",
        interval_minutes=1, weekdays="0,1,2,3,4,5,6",
    )
    db.add(s)
    await db.commit()

    # 钳住 should_fire=True，避免依赖真实当前时间
    monkeypatch.setattr(sch, "should_fire", lambda schedule, now_: True)

    calls = {"gen": 0, "bcast": 0}

    async def fake_generate(db_, persona, prompt):
        calls["gen"] += 1
        assert prompt == "测试提示词"
        return "fake msg"

    async def fake_broadcast(db_, persona, message):
        calls["bcast"] += 1
        assert message == "fake msg"
        return 3

    monkeypatch.setattr(sch, "generate_message", fake_generate)
    monkeypatch.setattr(sch, "broadcast", fake_broadcast)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    await sch._tick(session_factory=factory)
    assert calls == {"gen": 1, "bcast": 1}


async def test_tick_skips_disabled(db, monkeypatch, engine):
    from app.services import scheduler as sch

    p = Persona(slug="w", name="W", system_prompt="sys")
    db.add(p)
    await db.flush()
    s = PersonaSchedule(persona_id=p.id, enabled=0, prompt="x")
    db.add(s)
    await db.commit()

    calls = []

    async def fake_gen(*a, **kw):
        calls.append("gen")

    async def fake_bc(*a, **kw):
        calls.append("bcast")

    monkeypatch.setattr(sch, "generate_message", fake_gen)
    monkeypatch.setattr(sch, "broadcast", fake_bc)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    await sch._tick(session_factory=factory)
    assert calls == []
