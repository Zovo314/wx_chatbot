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


async def test_tick_isolates_ai_failure_per_schedule(db, monkeypatch, engine):
    """一个 schedule 的 AI 调用抛异常时，其它 schedule 仍应照常触发。"""
    from app.services import scheduler as sch

    p1 = Persona(slug="w1", name="W1", system_prompt="sys",
                 meta_json='{"kf":{"open_kfid":"kf1"}}')
    p2 = Persona(slug="w2", name="W2", system_prompt="sys",
                 meta_json='{"kf":{"open_kfid":"kf2"}}')
    db.add_all([p1, p2])
    await db.flush()
    db.add_all([
        PersonaSchedule(persona_id=p1.id, enabled=1, prompt="A"),
        PersonaSchedule(persona_id=p2.id, enabled=1, prompt="B"),
    ])
    await db.commit()

    monkeypatch.setattr(sch, "should_fire", lambda schedule, now_: True)

    bcast_calls = []

    async def flaky_generate(db_, persona, prompt):
        if prompt == "A":
            raise RuntimeError("AI down for A")
        return f"msg-{prompt}"

    async def fake_broadcast(db_, persona, message):
        bcast_calls.append((persona.slug, message))
        return 1

    monkeypatch.setattr(sch, "generate_message", flaky_generate)
    monkeypatch.setattr(sch, "broadcast", fake_broadcast)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    await sch._tick(session_factory=factory)
    # A 因为 AI 失败被跳过，B 仍然成功广播
    assert bcast_calls == [("w2", "msg-B")]


async def test_tick_skips_empty_generated_message(db, monkeypatch, engine):
    """generate_message 返回空字符串时 broadcast 不应被调用。"""
    from app.services import scheduler as sch

    p = Persona(slug="w", name="W", system_prompt="sys")
    db.add(p)
    await db.flush()
    db.add(PersonaSchedule(persona_id=p.id, enabled=1, prompt="x"))
    await db.commit()

    monkeypatch.setattr(sch, "should_fire", lambda schedule, now_: True)

    async def empty_generate(db_, persona, prompt):
        return ""

    bcast_calls = []

    async def fake_broadcast(db_, persona, message):
        bcast_calls.append(message)
        return 0

    monkeypatch.setattr(sch, "generate_message", empty_generate)
    monkeypatch.setattr(sch, "broadcast", fake_broadcast)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    await sch._tick(session_factory=factory)
    assert bcast_calls == []


async def test_tick_skips_schedule_whose_persona_was_deleted(db, monkeypatch, engine):
    """schedule 指向已删除 persona 时应安静跳过，不崩溃。"""
    from app.services import scheduler as sch

    # 直接建 schedule，指向不存在的 persona_id
    db.add(PersonaSchedule(persona_id=999999, enabled=1, prompt="x"))
    await db.commit()

    monkeypatch.setattr(sch, "should_fire", lambda schedule, now_: True)

    calls = []

    async def fake_generate(*a, **kw):
        calls.append("gen")

    async def fake_broadcast(*a, **kw):
        calls.append("bcast")

    monkeypatch.setattr(sch, "generate_message", fake_generate)
    monkeypatch.setattr(sch, "broadcast", fake_broadcast)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    await sch._tick(session_factory=factory)
    assert calls == []
