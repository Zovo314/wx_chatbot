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
