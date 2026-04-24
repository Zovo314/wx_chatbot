from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import PersonaSchedule
from app.services.scheduler import compute_fire_times, should_fire


def make(**kw):
    s = PersonaSchedule(persona_id=1)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_interval_every_hour_8_to_21():
    s = make(mode="interval", start_time="08:00", end_time="21:00", interval_minutes=60)
    times = compute_fire_times(s)
    assert times == {
        "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00",
        "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00",
    }
    assert len(times) == 14


def test_interval_every_30_min_window():
    s = make(mode="interval", start_time="08:00", end_time="09:00", interval_minutes=30)
    assert compute_fire_times(s) == {"08:00", "08:30", "09:00"}


def test_specific_times():
    s = make(mode="specific", specific_times='["07:30", "12:00", "22:30"]')
    assert compute_fire_times(s) == {"07:30", "12:00", "22:30"}


def test_specific_times_empty_on_bad_json():
    s = make(mode="specific", specific_times="not json")
    assert compute_fire_times(s) == set()


def test_should_fire_hits():
    s = make(enabled=1, mode="interval", start_time="08:00",
             end_time="21:00", interval_minutes=60, weekdays="0,1,2,3,4,5,6")
    now = datetime(2026, 4, 24, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))  # Fri 09:00
    assert should_fire(s, now) is True


def test_should_fire_misses_on_minute():
    s = make(enabled=1, mode="interval", start_time="08:00",
             end_time="21:00", interval_minutes=60, weekdays="0,1,2,3,4,5,6")
    now = datetime(2026, 4, 24, 9, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert should_fire(s, now) is False


def test_should_fire_skips_disabled():
    s = make(enabled=0, mode="interval", start_time="08:00",
             end_time="21:00", interval_minutes=60, weekdays="0,1,2,3,4,5,6")
    now = datetime(2026, 4, 24, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert should_fire(s, now) is False


def test_should_fire_respects_weekdays():
    # weekdays = 0,1,2,3,4 -> 周一到周五；4/25 是周六
    s = make(enabled=1, mode="interval", start_time="08:00",
             end_time="21:00", interval_minutes=60, weekdays="0,1,2,3,4")
    sat = datetime(2026, 4, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    fri = datetime(2026, 4, 24, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert should_fire(s, sat) is False
    assert should_fire(s, fri) is True
