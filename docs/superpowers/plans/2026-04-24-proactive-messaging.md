# 人格主动发送消息 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在创建/编辑 AI 人格时可勾选"主动发送消息"，按闹钟式时间表触发 AI 调用，按人格-客服绑定关系广播给该客服下 48 小时内活跃的外部客户。

**Architecture:** 纯增量改动 —— 新增 `PersonaSchedule` 表、`app/services/scheduler.py`（APScheduler 每分钟 tick）、`app/services/proactive.py`（生成 + 广播），在 `app/main.py` lifespan 启动调度器（失败不阻塞主服务）。触发后调用 1 次 AI 生成文本，广播给该人格绑定客服下的所有 48h 活跃 `external_userid`。

**Tech Stack:** FastAPI、SQLAlchemy async、SQLite、APScheduler `AsyncIOScheduler`、OpenAI 兼容 SDK、pytest + pytest-asyncio（测试新加）。

**约束（不可违反）:**
1. 所有现有表不加不改字段（只新增 `persona_schedules` 表）。
2. 所有现有路由/函数签名保持不变（只新增）。
3. 调度器启动失败、AI 调用失败、客服发送失败，**都不能阻塞主服务或让现有客服对话链路失败**（按现有 `_drain_kf_history` 的 try/except 惯例）。
4. 现有 `/admin/`、`/admin/create`、`/admin/kf`、`/wx/callback` 在本次改动后行为完全一致。

---

## File Structure

**Create（新增）:**
- `app/services/scheduler.py` — tick 循环 + fire 时刻计算 + 启停（~110 行）
- `app/services/proactive.py` — AI 生成 + 活跃客户查询 + 广播（~80 行）
- `tests/__init__.py` — 空文件
- `tests/conftest.py` — pytest 夹具（~30 行）
- `tests/test_scheduler_fire.py` — 纯函数测试（~60 行）
- `tests/test_proactive.py` — broadcast/活跃用户测试（~80 行）
- `requirements-dev.txt` — 测试依赖
- `docs/PROACTIVE.md` — 用户使用说明（简短）

**Modify（最小改动）:**
- `requirements.txt` — `+apscheduler>=3.10`
- `app/models.py` — `+PersonaSchedule` 类
- `app/database.py` — `init_db` 内 import 语句加 `PersonaSchedule`
- `app/main.py` — `lifespan` 末尾启动/关闭调度器
- `app/routers/admin.py` — 新增 3 个端点：保存 schedule、试发、详情页 context 加 schedule
- `app/templates/detail.html` — 底部新增"主动发送设置"区块

---

## Task 1: 搭建 pytest 基础设施

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1.1: 创建 dev 依赖文件**

```
# requirements-dev.txt
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 1.2: 创建 tests 包**

```python
# tests/__init__.py
```

（空文件）

- [ ] **Step 1.3: 创建 conftest.py**

```python
# tests/conftest.py
"""pytest 全局夹具。所有测试使用内存 SQLite，不碰生产库。"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # 触发 models.py 里所有模型注册到 metadata
    import app.models  # noqa: F401
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest.fixture(autouse=True)
def _disable_scheduler(monkeypatch):
    """测试中禁止真正的 APScheduler 启动，避免 TestClient 里后台线程干扰。
    Task 4 前 scheduler 模块还不存在，这里做 try/except 兜底。"""
    try:
        from app.services import scheduler as sch
        monkeypatch.setattr(sch, "start_scheduler", lambda: None, raising=False)
        monkeypatch.setattr(sch, "stop_scheduler", lambda: None, raising=False)
    except ImportError:
        pass
```

- [ ] **Step 1.4: 在仓库根创建 `pytest.ini`**

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 1.5: 安装并运行 pytest 验证基础设施**

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -v
```

Expected: `no tests ran in ...s`（0 个测试，但 pytest 正常启动，没有 ImportError）

- [ ] **Step 1.6: Commit**

```bash
git add requirements-dev.txt tests/ pytest.ini
git commit -m "chore: add pytest infrastructure for upcoming proactive-messaging feature"
```

---

## Task 2: 添加 APScheduler 依赖

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 2.1: 追加依赖**

在 `requirements.txt` 末尾追加：

```
# 主动发送调度器
apscheduler>=3.10
```

- [ ] **Step 2.2: 安装并验证**

```bash
python3 -m pip install -r requirements.txt
python3 -c "from apscheduler.schedulers.asyncio import AsyncIOScheduler; print('ok')"
```

Expected: `ok`

- [ ] **Step 2.3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add apscheduler dependency"
```

---

## Task 3: 新增 PersonaSchedule 模型

**Files:**
- Modify: `app/models.py`
- Modify: `app/database.py:16` (init_db 内 import)

- [ ] **Step 3.1: 在 `app/models.py` 末尾追加模型类**

```python
class PersonaSchedule(Base):
    """人格主动发送配置。每个人格至多一条（persona_id unique）。

    字段：
    - enabled: 0/1 是否启用
    - prompt: 给 AI 的提示词（system_prompt 之外的 user 指令）
    - mode: "interval"（起止+间隔）或 "specific"（指定时刻列表）
    - start_time / end_time: interval 模式用，格式 "HH:MM"
    - interval_minutes: interval 模式用，单位分钟
    - specific_times: specific 模式用，JSON 字符串如 '["07:30","12:00"]'
    - weekdays: 逗号分隔 "0,1,2,3,4,5,6"（0=周一，Python datetime.weekday() 定义）
    - timezone: IANA 时区名，默认 "Asia/Shanghai"
    """
    __tablename__ = "persona_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    enabled: Mapped[int] = mapped_column(Integer, default=0)
    prompt: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(20), default="interval")
    start_time: Mapped[str] = mapped_column(String(5), default="08:00")
    end_time: Mapped[str] = mapped_column(String(5), default="21:00")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    specific_times: Mapped[str] = mapped_column(Text, default="[]")
    weekdays: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4,5,6")
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
```

- [ ] **Step 3.2: 在 `app/database.py` 的 `init_db` 里把新模型 import 进来**

将第 16 行：

```python
    from app.models import Persona, Conversation, AIConfig  # noqa: F401
```

改为：

```python
    from app.models import Persona, Conversation, AIConfig, PersonaSchedule  # noqa: F401
```

- [ ] **Step 3.3: 写模型冒烟测试**

`tests/test_model_persona_schedule.py`：

```python
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
```

- [ ] **Step 3.4: 运行测试**

```bash
python3 -m pytest tests/test_model_persona_schedule.py -v
```

Expected: `1 passed`

- [ ] **Step 3.5: 验证现有启动流程不受影响（手动冒烟）**

```bash
rm -f data/ex.db  # 强制走一次完整 create_all + 迁移
python3 -c "
import asyncio
from app.database import init_db
asyncio.run(init_db())
print('init_db ok')
"
```

Expected: 打印 `init_db ok`，可能还有 `[migrate] ...` 这种原有日志；无异常。

- [ ] **Step 3.6: Commit**

```bash
git add app/models.py app/database.py tests/test_model_persona_schedule.py
git commit -m "feat(model): add PersonaSchedule table for proactive messaging"
```

---

## Task 4: 触发时刻纯函数 compute_fire_times / should_fire

**Files:**
- Create: `app/services/scheduler.py`（仅纯函数部分）
- Create: `tests/test_scheduler_fire.py`

- [ ] **Step 4.1: 写失败的测试**

```python
# tests/test_scheduler_fire.py
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
```

- [ ] **Step 4.2: 运行测试确认失败**

```bash
python3 -m pytest tests/test_scheduler_fire.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.scheduler'` 或类似，明确失败。

- [ ] **Step 4.3: 写最小实现（仅纯函数部分）**

```python
# app/services/scheduler.py
"""人格主动发送调度器：每分钟 tick → 扫 PersonaSchedule → 命中则广播。

触发模型：
- interval 模式：从 start_time 起到 end_time（含），每 interval_minutes 分钟触发一次
- specific 模式：specific_times 列表（JSON，"HH:MM" 数组）中的每个时刻触发一次
- 仅在 weekdays 覆盖的星期几触发（0=周一 ... 6=周日）
"""
import json
from datetime import datetime

from app.models import PersonaSchedule


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
```

- [ ] **Step 4.4: 运行测试验证通过**

```bash
python3 -m pytest tests/test_scheduler_fire.py -v
```

Expected: `8 passed`

- [ ] **Step 4.5: Commit**

```bash
git add app/services/scheduler.py tests/test_scheduler_fire.py
git commit -m "feat(scheduler): add compute_fire_times and should_fire pure functions"
```

---

## Task 5: 活跃客户查询 list_active_kf_users

**Files:**
- Create: `app/services/proactive.py`（仅此函数）
- Create: `tests/test_proactive.py`（仅此测试）

- [ ] **Step 5.1: 写失败的测试**

```python
# tests/test_proactive.py
from datetime import datetime, timezone, timedelta
import pytest

from app.models import Persona, Conversation

pytestmark = pytest.mark.asyncio


async def test_list_active_kf_users_filters_48h_and_kf_prefix(db):
    from app.services.proactive import list_active_kf_users

    p = Persona(slug="w", name="W", system_prompt="sys")
    db.add(p)
    await db.flush()

    now = datetime.now(timezone.utc)

    # 活跃：5 小时前的 kf 用户（保留）
    db.add(Conversation(persona_id=p.id, role="user",
                        content="hi", wx_user_id="kf_ext_A",
                        created_at=now - timedelta(hours=5)))
    # 活跃：重复的同一用户，去重后一次
    db.add(Conversation(persona_id=p.id, role="user",
                        content="hi2", wx_user_id="kf_ext_A",
                        created_at=now - timedelta(hours=1)))
    # 超窗：60h 前 -> 过滤
    db.add(Conversation(persona_id=p.id, role="user",
                        content="old", wx_user_id="kf_ext_B",
                        created_at=now - timedelta(hours=60)))
    # 非 kf 前缀（企微应用）-> 过滤
    db.add(Conversation(persona_id=p.id, role="user",
                        content="app", wx_user_id="app_user",
                        created_at=now - timedelta(hours=1)))
    # role=assistant -> 过滤（assistant 消息不代表用户活跃）
    db.add(Conversation(persona_id=p.id, role="assistant",
                        content="reply", wx_user_id="kf_ext_C",
                        created_at=now - timedelta(hours=1)))
    await db.commit()

    ids = await list_active_kf_users(db, p.id)
    assert set(ids) == {"ext_A"}
```

- [ ] **Step 5.2: 运行测试确认失败**

```bash
python3 -m pytest tests/test_proactive.py::test_list_active_kf_users_filters_48h_and_kf_prefix -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.proactive'`

- [ ] **Step 5.3: 写最小实现**

```python
# app/services/proactive.py
"""主动发送：AI 生成 + 广播到 48h 活跃的外部客服客户。"""
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Persona, Conversation


KF_WINDOW_HOURS = 47  # 客服 API 要求 48h 内有用户消息；留 1h 安全边际


async def list_active_kf_users(db: AsyncSession, persona_id: int) -> list[str]:
    """返回该人格 48h 内发过 user 消息的外部客户 external_userid（去前缀）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=KF_WINDOW_HOURS)
    result = await db.execute(
        select(Conversation.wx_user_id)
        .where(
            Conversation.persona_id == persona_id,
            Conversation.role == "user",
            Conversation.created_at >= cutoff,
            Conversation.wx_user_id.like("kf_%"),
        )
        .distinct()
    )
    out: list[str] = []
    seen: set[str] = set()
    for (wid,) in result.all():
        if not wid:
            continue
        ext = wid[3:]  # 去掉 "kf_" 前缀
        if ext and ext not in seen:
            seen.add(ext)
            out.append(ext)
    return out
```

- [ ] **Step 5.4: 运行测试验证通过**

```bash
python3 -m pytest tests/test_proactive.py::test_list_active_kf_users_filters_48h_and_kf_prefix -v
```

Expected: `1 passed`

- [ ] **Step 5.5: Commit**

```bash
git add app/services/proactive.py tests/test_proactive.py
git commit -m "feat(proactive): add list_active_kf_users (48h window, distinct)"
```

---

## Task 6: AI 生成消息 generate_message

**Files:**
- Modify: `app/services/proactive.py`
- Modify: `tests/test_proactive.py`

- [ ] **Step 6.1: 追加失败测试**

把以下内容追加到 `tests/test_proactive.py` 末尾：

```python
async def test_generate_message_builds_correct_prompt_and_sanitizes(db, monkeypatch):
    from app.services import proactive as mod
    from app.models import AIConfig, Persona

    # 注入默认 AIConfig，避免 get_ai_config 去读生产 env
    db.add(AIConfig(id=1, provider="openai", model="gpt-4o",
                    api_key="k", base_url="https://x", max_history=20))
    p = Persona(slug="w", name="喝水助手", system_prompt="你是一个关心用户的小助手")
    db.add(p)
    await db.commit()
    await db.refresh(p)

    captured = {}

    async def fake_chat_completion(config, messages):
        captured["config"] = config
        captured["messages"] = messages
        return "（温柔地说）喝水助手：该喝水啦~"

    monkeypatch.setattr(mod, "chat_completion", fake_chat_completion)

    reply = await mod.generate_message(db, p, "提醒用户喝水")

    # 验证 system + user 两条消息，user 里带提示词
    assert len(captured["messages"]) == 2
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][0]["content"] == "你是一个关心用户的小助手"
    assert captured["messages"][1]["role"] == "user"
    assert "提醒用户喝水" in captured["messages"][1]["content"]

    # 验证 sanitize：去括号旁白 + 去名字前缀
    assert "（" not in reply and "喝水助手：" not in reply
    assert "该喝水啦" in reply
```

- [ ] **Step 6.2: 运行测试确认失败**

```bash
python3 -m pytest tests/test_proactive.py::test_generate_message_builds_correct_prompt_and_sanitizes -v
```

Expected: `AttributeError` 或 `ImportError` —— `generate_message` 不存在。

- [ ] **Step 6.3: 在 `app/services/proactive.py` 顶部 import 区补 import，文件末尾追加实现**

在文件顶部（现有 imports 之后）追加：

```python
from app.services.ai_client import chat_completion
from app.services.chat import get_ai_config, _sanitize_reply
```

在文件末尾追加：

```python
async def generate_message(db: AsyncSession, persona: Persona, user_prompt: str) -> str:
    """按 system_prompt + user_prompt 调 AI 生成一条主动消息，并做 sanitize。"""
    config = await get_ai_config(db)
    instruction = (
        "请按以下要求生成一条主动发送给用户的消息，"
        "语气符合你的人设，直接输出消息内容本身，"
        "不要添加任何旁白、括号、角色名前缀或额外说明：\n\n"
        f"{user_prompt}"
    )
    messages = [
        {"role": "system", "content": persona.system_prompt or ""},
        {"role": "user", "content": instruction},
    ]
    reply = await chat_completion(config, messages)
    return _sanitize_reply(reply, persona.name)
```

- [ ] **Step 6.4: 运行测试验证通过**

```bash
python3 -m pytest tests/test_proactive.py -v
```

Expected: 2 passed（之前那个 + 新加的）。

- [ ] **Step 6.5: Commit**

```bash
git add app/services/proactive.py tests/test_proactive.py
git commit -m "feat(proactive): add generate_message (system=persona, user=prompt) + sanitize"
```

---

## Task 7: 广播 broadcast

**Files:**
- Modify: `app/services/proactive.py`
- Modify: `tests/test_proactive.py`

- [ ] **Step 7.1: 追加失败测试**

追加到 `tests/test_proactive.py`：

```python
async def test_broadcast_sends_to_all_active_users(db, monkeypatch):
    from app.services import proactive as mod
    from app.models import Persona, Conversation
    from datetime import datetime, timezone, timedelta

    p = Persona(
        slug="w", name="W", system_prompt="sys",
        meta_json='{"kf":{"open_kfid":"kf123","link":"x"}}',
    )
    db.add(p)
    await db.flush()
    now = datetime.now(timezone.utc)
    for ext in ("a", "b", "c"):
        db.add(Conversation(persona_id=p.id, role="user", content="hi",
                            wx_user_id=f"kf_{ext}",
                            created_at=now - timedelta(hours=2)))
    await db.commit()

    sent = []

    async def fake_send(open_kfid, external_userid, content):
        sent.append((open_kfid, external_userid, content))

    monkeypatch.setattr(mod, "send_kf_message", fake_send)

    n = await mod.broadcast(db, p, "hello")
    assert n == 3
    assert {s[1] for s in sent} == {"a", "b", "c"}
    assert all(s[0] == "kf123" for s in sent)
    assert all(s[2] == "hello" for s in sent)


async def test_broadcast_skips_when_no_kf_binding(db, monkeypatch):
    from app.services import proactive as mod
    from app.models import Persona

    p = Persona(slug="w", name="W", system_prompt="sys", meta_json="{}")
    db.add(p)
    await db.commit()

    calls = []

    async def fake_send(*a, **kw):
        calls.append(a)

    monkeypatch.setattr(mod, "send_kf_message", fake_send)
    n = await mod.broadcast(db, p, "hello")
    assert n == 0
    assert calls == []


async def test_broadcast_continues_on_per_user_error(db, monkeypatch):
    from app.services import proactive as mod
    from app.models import Persona, Conversation
    from datetime import datetime, timezone, timedelta

    p = Persona(slug="w", name="W", system_prompt="sys",
                meta_json='{"kf":{"open_kfid":"kf1"}}')
    db.add(p)
    await db.flush()
    now = datetime.now(timezone.utc)
    for ext in ("a", "b", "c"):
        db.add(Conversation(persona_id=p.id, role="user", content="hi",
                            wx_user_id=f"kf_{ext}",
                            created_at=now - timedelta(hours=2)))
    await db.commit()

    async def flaky(open_kfid, external_userid, content):
        if external_userid == "b":
            raise RuntimeError("network down")

    monkeypatch.setattr(mod, "send_kf_message", flaky)
    n = await mod.broadcast(db, p, "hello")
    assert n == 2  # a 和 c 成功，b 失败
```

- [ ] **Step 7.2: 运行测试确认失败**

```bash
python3 -m pytest tests/test_proactive.py -v -k broadcast
```

Expected: 3 个测试全部失败（`broadcast` / `send_kf_message` 未从 proactive 模块导出）。

- [ ] **Step 7.3: 实现 broadcast**

在 `app/services/proactive.py` 顶部 import 区追加：

```python
from app.services.kf import send_kf_message
```

在文件末尾追加：

```python
async def broadcast(db: AsyncSession, persona: Persona, message: str) -> int:
    """把一条消息广播给该人格绑定的客服下 48h 活跃的所有外部客户。
    返回成功发送的条数。无绑定、无活跃用户或空消息时返回 0，不抛异常。
    """
    if not message or not message.strip():
        return 0
    try:
        meta = json.loads(persona.meta_json) if persona.meta_json else {}
    except Exception:
        meta = {}
    open_kfid = (meta.get("kf") or {}).get("open_kfid")
    if not open_kfid:
        print(f"[主动] {persona.slug} 未绑定客服，跳过")
        return 0

    user_ids = await list_active_kf_users(db, persona.id)
    if not user_ids:
        print(f"[主动] {persona.slug} 无 48h 活跃客户，跳过")
        return 0

    sent = 0
    for uid in user_ids:
        try:
            await send_kf_message(open_kfid, uid, message)
            sent += 1
        except Exception as e:
            print(f"[主动] 发送失败 persona={persona.slug} uid={uid}: {e}")
    print(f"[主动] {persona.slug} 广播完成: {sent}/{len(user_ids)}")
    return sent
```

- [ ] **Step 7.4: 运行测试**

```bash
python3 -m pytest tests/test_proactive.py -v
```

Expected: 5 passed（总共）。

- [ ] **Step 7.5: Commit**

```bash
git add app/services/proactive.py tests/test_proactive.py
git commit -m "feat(proactive): add broadcast with isolated per-user error handling"
```

---

## Task 8: 调度器 _tick 集成

**Files:**
- Modify: `app/services/scheduler.py`
- Create: `tests/test_scheduler_tick.py`

_tick 设计为接受可注入的 `session_factory` 参数（默认 `async_session`），这样测试可以用 fixture 里的 in-memory engine 工厂，既干净又无 flakiness。

- [ ] **Step 8.1: 写失败的测试**

```python
# tests/test_scheduler_tick.py
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
```

- [ ] **Step 8.2: 运行测试确认失败**

```bash
python3 -m pytest tests/test_scheduler_tick.py -v
```

Expected: `_tick` 未定义或不接受 `session_factory`，全部失败。

- [ ] **Step 8.3: 在 `app/services/scheduler.py` 追加 _tick 和启停**

在文件顶部 imports 区之后追加：

```python
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import async_session
from app.services.proactive import broadcast, generate_message
```

在文件末尾追加：

```python
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
```

- [ ] **Step 8.4: 运行测试验证通过**

```bash
python3 -m pytest tests/test_scheduler_tick.py -v
```

Expected: `2 passed`

- [ ] **Step 8.5: Commit**

```bash
git add app/services/scheduler.py tests/test_scheduler_tick.py
git commit -m "feat(scheduler): add _tick that scans schedules and fires on match"
```

---

## Task 9: 启停调度器并接入 lifespan

**Files:**
- Modify: `app/services/scheduler.py`
- Modify: `app/main.py`

- [ ] **Step 9.1: 在 `app/services/scheduler.py` 末尾追加启停函数**

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


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
```

并把 scheduler.py 顶部 imports 合并成这份最终版（替换 Task 4 和 Task 8 已写的 imports）：

```python
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import async_session
from app.models import PersonaSchedule
from app.services.proactive import broadcast, generate_message
```

- [ ] **Step 9.2: 修改 `app/main.py::lifespan`**

把现有的 `lifespan` 改为：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # 客服模块失败不应阻塞主服务启动
    try:
        await _restore_kf_bindings()
        await _drain_kf_history()
    except Exception as e:
        print(f"[启动] 客服模块初始化失败（忽略，主服务继续）: {e}")
    # 主动发送调度器失败也不应阻塞主服务启动
    try:
        from app.services.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"[启动] 主动发送调度器启动失败（忽略，主服务继续）: {e}")
    yield
    try:
        from app.services.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
```

- [ ] **Step 9.3: 冒烟：启动/停止调度器不抛异常**

```bash
python3 -c "
import asyncio
from app.services.scheduler import start_scheduler, stop_scheduler

async def main():
    loop = asyncio.get_event_loop()
    start_scheduler()
    await asyncio.sleep(0.1)
    stop_scheduler()

asyncio.run(main())
print('ok')
"
```

Expected: 打印两行 `[调度] ...` 日志 + `ok`，无异常。

- [ ] **Step 9.4: 冒烟：完整应用启动—关停不异常**

```bash
timeout 5 python3 -c "
import asyncio
from app.main import app
from fastapi.testclient import TestClient
with TestClient(app) as client:
    r = client.get('/')
    print('status:', r.status_code)
"
```

Expected: `status: 200` 或 `307`（重定向到 /admin/）；看到启动日志 `[调度] 主动发送调度器已启动（每分钟 tick）`；进程正常退出。

- [ ] **Step 9.5: 运行所有单元测试确保没坏现有测试**

```bash
python3 -m pytest -v
```

Expected: 所有测试 passed（约 11 个）。

- [ ] **Step 9.6: Commit**

```bash
git add app/services/scheduler.py app/main.py
git commit -m "feat(scheduler): wire start/stop into FastAPI lifespan (non-blocking)"
```

---

## Task 10: Admin 路由 —— 保存 schedule

**Files:**
- Modify: `app/routers/admin.py`

- [ ] **Step 10.1: 在 `app/routers/admin.py` 末尾追加端点**

```python
# -------- 主动发送设置 --------
@router.post("/detail/{slug}/schedule")
async def save_schedule(
    slug: str,
    enabled: str = Form("0"),
    prompt: str = Form(""),
    mode: str = Form("interval"),
    start_time: str = Form("08:00"),
    end_time: str = Form("21:00"),
    interval_minutes: int = Form(60),
    specific_times: str = Form("[]"),
    weekdays: str = Form("0,1,2,3,4,5,6"),
    timezone: str = Form("Asia/Shanghai"),
    db: AsyncSession = Depends(get_db),
):
    from app.models import PersonaSchedule
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "persona not found")

    result = await db.execute(
        select(PersonaSchedule).where(PersonaSchedule.persona_id == p.id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        s = PersonaSchedule(persona_id=p.id)
        db.add(s)

    s.enabled = 1 if str(enabled).lower() in ("1", "true", "on", "yes") else 0
    s.prompt = (prompt or "").strip()
    s.mode = mode if mode in ("interval", "specific") else "interval"
    s.start_time = start_time or "08:00"
    s.end_time = end_time or "21:00"
    s.interval_minutes = max(1, int(interval_minutes or 60))
    s.specific_times = specific_times or "[]"
    s.weekdays = weekdays or "0,1,2,3,4,5,6"
    s.timezone = timezone or "Asia/Shanghai"
    await db.commit()
    return RedirectResponse(url=f"/admin/detail/{slug}", status_code=303)
```

- [ ] **Step 10.2: 集成测试（TestClient）**

创建 `tests/test_admin_schedule.py`：

```python
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
```

- [ ] **Step 10.3: 运行测试**

```bash
python3 -m pytest tests/test_admin_schedule.py -v
```

Expected: `2 passed`

- [ ] **Step 10.4: Commit**

```bash
git add app/routers/admin.py tests/test_admin_schedule.py
git commit -m "feat(admin): add POST /admin/detail/{slug}/schedule (upsert)"
```

---

## Task 11: Admin 路由 —— 手动试发

**Files:**
- Modify: `app/routers/admin.py`

- [ ] **Step 11.1: 追加端点（放在 Task 10 的 save_schedule 之后）**

```python
@router.post("/detail/{slug}/schedule/test")
async def test_schedule(slug: str, db: AsyncSession = Depends(get_db)):
    """手动试发一条主动消息。用于 UI 调试。"""
    from app.models import PersonaSchedule
    from app.services.proactive import generate_message, broadcast
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "persona not found")

    result = await db.execute(
        select(PersonaSchedule).where(PersonaSchedule.persona_id == p.id)
    )
    s = result.scalar_one_or_none()
    if s is None or not s.prompt.strip():
        return JSONResponse(
            {"ok": False, "error": "未配置主动发送或提示词为空"}, status_code=400
        )

    try:
        message = await generate_message(db, p, s.prompt)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"AI 生成失败: {e}"}, status_code=500)

    sent = await broadcast(db, p, message)
    return JSONResponse({"ok": True, "message": message, "sent": sent})
```

- [ ] **Step 11.2: 追加测试到 `tests/test_admin_schedule.py`**

```python
async def test_schedule_test_endpoint(engine, monkeypatch):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        p = Persona(slug="w", name="W", system_prompt="sys",
                    meta_json='{"kf":{"open_kfid":"kf1"}}')
        db.add(p)
        await db.flush()
        db.add(PersonaSchedule(persona_id=p.id, enabled=1, prompt="喝水吧"))
        await db.commit()

    from app.services import proactive
    async def fake_gen(db_, persona, prompt):
        return f"[AI] {prompt}"
    async def fake_bc(db_, persona, message):
        return 7
    monkeypatch.setattr(proactive, "generate_message", fake_gen)
    monkeypatch.setattr(proactive, "broadcast", fake_bc)

    async def _override_get_db():
        async with Session() as session:
            yield session
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            r = client.post("/admin/detail/w/schedule/test")
            assert r.status_code == 200
            data = r.json()
            assert data["ok"] is True
            assert data["message"] == "[AI] 喝水吧"
            assert data["sent"] == 7
    finally:
        app.dependency_overrides.clear()


async def test_schedule_test_without_prompt_returns_400(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        p = Persona(slug="w", name="W", system_prompt="sys")
        db.add(p)
        await db.flush()
        db.add(PersonaSchedule(persona_id=p.id, enabled=1, prompt="   "))
        await db.commit()

    async def _override_get_db():
        async with Session() as session:
            yield session
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            r = client.post("/admin/detail/w/schedule/test")
            assert r.status_code == 400
            assert r.json()["ok"] is False
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 11.3: 运行测试**

```bash
python3 -m pytest tests/test_admin_schedule.py -v
```

Expected: `4 passed`（原 2 + 新 2）。

- [ ] **Step 11.4: Commit**

```bash
git add app/routers/admin.py tests/test_admin_schedule.py
git commit -m "feat(admin): add manual test-send endpoint for schedule"
```

---

## Task 12: Admin 详情页加载 schedule

**Files:**
- Modify: `app/routers/admin.py:276-288` (detail_page 函数)

- [ ] **Step 12.1: 修改 detail_page**

找到 `async def detail_page(`，把函数体内最后的 return 改为：

```python
@router.get("/detail/{slug}", response_class=HTMLResponse)
async def detail_page(
    request: Request, slug: str, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    persona = result.scalar_one_or_none()
    if not persona:
        return RedirectResponse(url="/admin/")
    meta = json.loads(persona.meta_json) if persona.meta_json else {}

    from app.models import PersonaSchedule
    result = await db.execute(
        select(PersonaSchedule).where(PersonaSchedule.persona_id == persona.id)
    )
    schedule = result.scalar_one_or_none()

    return templates.TemplateResponse(
        request, name="detail.html",
        context={"persona": persona, "meta": meta, "schedule": schedule},
    )
```

- [ ] **Step 12.2: 手动冒烟（不改 detail.html 也应正常渲染：schedule=None 时现有模板照常显示）**

```bash
# 建一个虚拟 persona 并访问详情页
timeout 5 python3 -c "
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.database import async_session
from app.models import Persona

async def seed():
    async with async_session() as db:
        db.add(Persona(slug='zz_test', name='test', system_prompt='sys'))
        await db.commit()

async def cleanup():
    from sqlalchemy import select
    async with async_session() as db:
        r = await db.execute(select(Persona).where(Persona.slug=='zz_test'))
        p = r.scalar_one_or_none()
        if p:
            await db.delete(p)
            await db.commit()

asyncio.run(seed())
with TestClient(app) as client:
    r = client.get('/admin/detail/zz_test')
    print('status:', r.status_code)
    assert r.status_code == 200, r.text[:500]
asyncio.run(cleanup())
print('ok')
"
```

Expected: `status: 200` 后打印 `ok`。现有详情页内容未变。

- [ ] **Step 12.3: Commit**

```bash
git add app/routers/admin.py
git commit -m "feat(admin): load PersonaSchedule into detail page context"
```

---

## Task 13: Detail 页面加"主动发送设置"区块

**Files:**
- Modify: `app/templates/detail.html`

- [ ] **Step 13.1: 在 `<form method="post" action="/admin/detail/{{ persona.slug }}/delete"` 之前插入整段区块**

具体位置：在当前文件第 67 行（`<form method="post" action="/admin/detail/{{ persona.slug }}/delete"...`）之前。

```html
<h2>主动发送设置</h2>
<form method="post" action="/admin/detail/{{ persona.slug }}/schedule" id="schedule-form" style="border:1px solid #eee;border-radius:6px;padding:14px;">
  <label style="display:flex;align-items:center;gap:8px;">
    <input type="checkbox" name="enabled" value="1" {% if schedule and schedule.enabled %}checked{% endif %}>
    <span>启用主动发送</span>
  </label>

  <label style="display:block;margin-top:10px;font-size:13px;color:#555;">
    AI 提示词（每次到点，系统会用此提示词调一次 AI，按人设生成一条消息广播给 48 小时内活跃的外部客户）
    <textarea name="prompt" rows="2" style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px;box-sizing:border-box;font-family:inherit;" placeholder="例：提醒用户喝水">{% if schedule %}{{ schedule.prompt }}{% endif %}</textarea>
  </label>

  <div style="margin-top:10px;">
    <label style="margin-right:16px;"><input type="radio" name="mode" value="interval" {% if not schedule or schedule.mode == 'interval' %}checked{% endif %}> 间隔模式</label>
    <label><input type="radio" name="mode" value="specific" {% if schedule and schedule.mode == 'specific' %}checked{% endif %}> 指定时刻</label>
  </div>

  <div id="mode-interval" style="margin-top:8px;">
    <label style="display:inline-block;margin-right:10px;">开始
      <input type="time" name="start_time" value="{% if schedule %}{{ schedule.start_time }}{% else %}08:00{% endif %}">
    </label>
    <label style="display:inline-block;margin-right:10px;">结束
      <input type="time" name="end_time" value="{% if schedule %}{{ schedule.end_time }}{% else %}21:00{% endif %}">
    </label>
    <label style="display:inline-block;">间隔（分钟）
      <input type="number" name="interval_minutes" min="1" style="width:80px;" value="{% if schedule %}{{ schedule.interval_minutes }}{% else %}60{% endif %}">
    </label>
  </div>

  <div id="mode-specific" style="margin-top:8px;display:none;">
    <label style="display:block;">时刻列表（JSON 数组，例：["07:30","12:00","22:30"]）
      <input type="text" name="specific_times" style="width:100%;padding:8px 10px;border:1px solid #ddd;border-radius:6px;" value='{% if schedule %}{{ schedule.specific_times }}{% else %}[]{% endif %}'>
    </label>
  </div>

  <div style="margin-top:10px;">
    <div style="font-size:13px;color:#555;margin-bottom:4px;">重复日</div>
    <div id="weekdays-box">
      {% set wd_set = (schedule.weekdays if schedule else '0,1,2,3,4,5,6').split(',') %}
      {% for pair in [('0','一'),('1','二'),('2','三'),('3','四'),('4','五'),('5','六'),('6','日')] %}
      <label style="display:inline-block;margin-right:10px;">
        <input type="checkbox" class="wd" value="{{ pair[0] }}" {% if pair[0] in wd_set %}checked{% endif %}>
        周{{ pair[1] }}
      </label>
      {% endfor %}
      <input type="hidden" name="weekdays" id="weekdays-value">
    </div>
  </div>

  <label style="display:block;margin-top:10px;">时区
    <input type="text" name="timezone" value="{% if schedule %}{{ schedule.timezone }}{% else %}Asia/Shanghai{% endif %}" style="width:200px;">
  </label>

  <div class="row">
    <button type="submit">保存设置</button>
    <button type="button" onclick="testSchedule('{{ persona.slug }}')">试发一条</button>
  </div>

  <div class="small" style="margin-top:8px;">
    提示：客户 48 小时内未回复任何消息时，主动消息会被微信拒发（自动静默跳过）。客户只需回复任意一条即可续上窗口。
  </div>
</form>

<script>
function collectWeekdays() {
  const vals = [...document.querySelectorAll('#weekdays-box .wd:checked')].map(c => c.value);
  document.getElementById('weekdays-value').value = vals.join(',');
}
document.getElementById('schedule-form').addEventListener('submit', collectWeekdays);

function updateModeVisibility() {
  const sel = document.querySelector('input[name="mode"]:checked');
  const v = sel ? sel.value : 'interval';
  document.getElementById('mode-interval').style.display = v === 'interval' ? '' : 'none';
  document.getElementById('mode-specific').style.display = v === 'specific' ? '' : 'none';
}
document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener('change', updateModeVisibility));
updateModeVisibility();

async function testSchedule(slug) {
  collectWeekdays();
  const fd = new FormData(document.getElementById('schedule-form'));
  // 先保存一次最新配置，避免用旧数据试发
  await fetch(`/admin/detail/${slug}/schedule`, { method: 'POST', body: fd });
  const resp = await fetch(`/admin/detail/${slug}/schedule/test`, { method: 'POST' });
  const data = await resp.json().catch(() => ({ok:false, error:'响应非 JSON'}));
  if (data.ok) {
    alert(`AI 生成内容：\n\n${data.message}\n\n已发送给 ${data.sent} 位 48h 内活跃客户。`);
  } else {
    alert('试发失败：' + (data.error || '未知错误'));
  }
}
</script>
```

- [ ] **Step 13.2: 启动服务手动冒烟**

```bash
uvicorn app.main:app --port 8765 &
SERVER_PID=$!
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8765/admin/ || true
kill $SERVER_PID 2>/dev/null
```

Expected: `200` 或 `307`。

然后用浏览器访问 `http://localhost:8765/admin/detail/<某个已有 slug>`，确认：
1. 原有 "System Prompt / 各维度 / 原始 Memory / 原始 Persona" 区块照常显示
2. 新增"主动发送设置"表单显示
3. 勾选"启用"、填 prompt "提醒用户喝水"、选间隔 60 分钟、8:00–21:00、周一到周日全勾，点"保存设置"，页面重定向回详情页，勾选和填写值保留
4. 切换"指定时刻"单选，interval 控件隐藏，specific 控件显示
5. 点"试发一条"——若该人格未绑定客服或无 48h 活跃客户，alert 会显示 `sent=0` 但 `message` 有 AI 生成内容；若都就绪，真的会被发出去。

- [ ] **Step 13.3: Commit**

```bash
git add app/templates/detail.html
git commit -m "feat(ui): add proactive messaging form section on persona detail page"
```

---

## Task 14: 回归冒烟 + 文档

**Files:**
- Create: `docs/PROACTIVE.md`

- [ ] **Step 14.1: 跑全量测试**

```bash
python3 -m pytest -v
```

Expected: 全部 passed（约 15 个）。

- [ ] **Step 14.2: 手动回归——现有功能不受影响**

依次验证（用浏览器或 curl）：

```bash
uvicorn app.main:app --port 8765 &
SERVER_PID=$!
sleep 2

# 人格列表页
curl -s -o /dev/null -w "GET /admin/ -> %{http_code}\n" http://localhost:8765/admin/

# 创建选择类型页
curl -s -o /dev/null -w "GET /admin/create -> %{http_code}\n" http://localhost:8765/admin/create

# 创建 private 表单
curl -s -o /dev/null -w "GET /admin/create/private -> %{http_code}\n" http://localhost:8765/admin/create/private

# 微信客服页
curl -s -o /dev/null -w "GET /admin/kf -> %{http_code}\n" http://localhost:8765/admin/kf

# AI 配置页
curl -s -o /dev/null -w "GET /admin/config -> %{http_code}\n" http://localhost:8765/admin/config

# 根路径重定向
curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://localhost:8765/

kill $SERVER_PID 2>/dev/null
```

Expected: 所有状态码均为 200 或 3xx。**任何 5xx 都是回归。**

- [ ] **Step 14.3: 启动日志检查**

启动时 stdout 中应至少包含：

```
[调度] 主动发送调度器已启动（每分钟 tick）
```

且不能有 tracebacks。如果没装 apscheduler 不会发生（Task 2 已安装），若不小心缺失应看到 `[启动] 主动发送调度器启动失败（忽略，主服务继续）: ...` 而不是进程崩溃。

- [ ] **Step 14.4: 写简短文档**

```markdown
# docs/PROACTIVE.md
# 主动发送消息

## 使用流程
1. 在 `/admin/create/*` 正常创建一个 AI 人格（例：喝水助手）。
2. 在 `/admin/kf` 把人格绑定到企业微信客服账号。
3. 进入 `/admin/detail/<slug>`，滚到"主动发送设置"。
4. 勾选"启用"，填写 AI 提示词（如 `提醒用户喝水`），选择时间表：
   - 间隔模式：起始 `08:00`、结束 `21:00`、间隔 `60` 分钟 → 每天 14 次触发
   - 指定时刻模式：填 JSON，如 `["07:30","12:00","22:30"]`
5. 勾选重复日（默认每日），时区默认 `Asia/Shanghai`。
6. 点"保存设置"。可点"试发一条"立刻验证。

## 工作原理
- 后台调度器每分钟扫一次 `persona_schedules` 表。
- 命中触发时刻后，调 1 次 AI 用 `system=人格 system_prompt + user=提示词` 生成一条文本。
- 文本广播到该人格绑定客服下所有 **48 小时内**跟该人格聊过的外部客户。
- **48 小时静默规则**：客户 48 小时内未回复任何消息时，微信会拒发；系统自动跳过，写日志。
- 客户只要回一条任意内容（如"收到"），48h 窗口就会续上。

## 故障排查
- **试发 `sent=0`**：通常是客户从未与该客服聊过（没有 `kf_*` 的 Conversation 记录），或所有客户都超过 48 小时没发消息。
- **AI 生成失败**：检查 `/admin/config` 的 API Key、Base URL、Model。
- **没有启动日志 `[调度] 主动发送调度器已启动`**：查启动 stdout 的 `[启动] 主动发送调度器启动失败` 原因（通常是缺依赖）。
```

- [ ] **Step 14.5: Commit**

```bash
git add docs/PROACTIVE.md
git commit -m "docs: usage guide for proactive messaging"
```

- [ ] **Step 14.6: 最后再跑一次全量**

```bash
python3 -m pytest -v && echo "ALL GREEN"
```

Expected: 看到 `ALL GREEN`。

---

## 附录：回滚路径（应急）

如果生产有任何问题需要回滚，只需：

```bash
git revert <本次所有提交>  # 或
git reset --hard <本次前的 commit SHA>
```

因为所有改动都是**纯增量**，回滚后数据库里多出来的 `persona_schedules` 表不会被任何代码查询，可安全保留或手动 `DROP TABLE`。
