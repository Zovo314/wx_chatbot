import pytest

pytestmark = pytest.mark.asyncio


async def test_persona_schedule_defaults(db):
    from app.models import PersonaSchedule
    s = PersonaSchedule(persona_id=1)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    assert s.enabled == 0
    assert s.mode == "interval"
    assert s.start_time == "08:00"
    assert s.end_time == "21:00"
    assert s.interval_minutes == 60
    assert s.specific_times == "[]"
    assert s.weekdays == "0,1,2,3,4,5,6"
    assert s.timezone == "Asia/Shanghai"
