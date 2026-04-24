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
