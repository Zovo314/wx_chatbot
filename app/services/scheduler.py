"""人格主动发送调度器：每分钟 tick → 扫 PersonaSchedule → 命中则广播。

触发模型：
- interval 模式：从 start_time 起到 end_time（含），每 interval_minutes 分钟触发一次
- specific 模式：specific_times 列表（JSON，"HH:MM" 数组）中的每个时刻触发一次
- 仅在 weekdays 覆盖的星期几触发（0=周一 ... 6=周日）
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import async_session
from app.models import PersonaSchedule
from app.services.proactive import broadcast, generate_message


def compute_fire_times(s: PersonaSchedule) -> set[str]:
    """返回 schedule 在一天中的所有触发时刻（"HH:MM" 字符串）。"""
    if s.mode == "specific":
        try:
            arr = json.loads(s.specific_times or "[]")
            return {str(t).strip() for t in arr if t}
        except Exception:
            return set()
    # interval 模式
    try:
        sh, sm = map(int, s.start_time.split(":"))
        eh, em = map(int, s.end_time.split(":"))
    except Exception:
        return set()
    step = max(1, int(s.interval_minutes or 60))
    result: set[str] = set()
    t = sh * 60 + sm
    end = eh * 60 + em
    while t <= end:
        result.add(f"{t // 60:02d}:{t % 60:02d}")
        t += step
    return result


def should_fire(s: PersonaSchedule, now: datetime) -> bool:
    """判断当前时间是否应触发该 schedule。

    now 必须带 tzinfo（调用方应用 s.timezone 解析）。
    """
    if not s.enabled:
        return False
    wds = [w.strip() for w in (s.weekdays or "").split(",") if w.strip()]
    if str(now.weekday()) not in wds:
        return False
    hm = now.strftime("%H:%M")
    return hm in compute_fire_times(s)


async def _tick(session_factory=None):
    """每分钟执行：扫 enabled schedule，命中则 generate → broadcast。"""
    factory = session_factory or async_session
    try:
        async with factory() as db:
            rows = await db.execute(select(PersonaSchedule).where(PersonaSchedule.enabled == 1))
            schedules = rows.scalars().all()
            for s in schedules:
                try:
                    tz = ZoneInfo(s.timezone or "Asia/Shanghai")
                    now_local = datetime.now(tz)
                    if not should_fire(s, now_local):
                        continue
                    from app.models import Persona
                    persona = await db.get(Persona, s.persona_id)
                    if not persona:
                        continue
                    msg = await generate_message(db, persona, s.prompt)
                    if not msg:
                        continue
                    await broadcast(db, persona, msg)
                except Exception as e:
                    print(f"[调度] schedule_id={s.id} 执行异常（忽略）: {e}")
    except Exception as e:
        print(f"[调度] tick 顶层异常（忽略）: {e}")


_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler | None:
    """启动每分钟 tick 的调度器；若已启动则返回现有实例。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(
        _tick,
        CronTrigger(minute="*", timezone="UTC"),
        id="proactive_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    print("[调度] 主动发送调度器已启动（每分钟 tick）")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
        print("[调度] 主动发送调度器已停止")
