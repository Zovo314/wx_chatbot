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
    # SQL LIKE 下划线回归：'kfX_xxx' 不应匹配 —— 必须严格以 "kf_" 开头
    db.add(Conversation(persona_id=p.id, role="user",
                        content="fake", wx_user_id="kfXbad",
                        created_at=now - timedelta(hours=1)))
    await db.commit()

    ids = await list_active_kf_users(db, p.id)
    assert set(ids) == {"ext_A"}


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
