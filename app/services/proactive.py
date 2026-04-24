"""主动发送：AI 生成 + 广播到 48h 活跃的外部客服客户。"""
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Persona, Conversation

from app.services.ai_client import chat_completion
from app.services.chat import get_ai_config, _sanitize_reply
from app.services.kf import send_kf_message


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
