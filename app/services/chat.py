"""对话管理服务：拼装历史 + 调 AI + 存储对话记录。"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Persona, Conversation, AIConfig
from app.services.ai_client import chat_completion


def _sanitize_reply(reply: str, name: str) -> str:
    """对 AI 回复做后处理，去除格式污染。

    处理项：
    1. 去除括号旁白/场景描写（中文/英文括号）
    2. 去除名字前缀（如"A："/"A:"/"【A】"/"[A]"），支持多行反复出现
    3. 去除首尾引号包裹（AI 偶尔会把整条回复用引号包起来）
    4. 清理多余空行和首尾空白
    """
    # 1. 去掉括号旁白/场景描写
    reply = re.sub(r'[（\(][^）\)]*[）\)]', '', reply)

    # 2. 去除名字前缀（可能出现在开头，也可能每行都有）
    # 支持形式：A： / A: / 【A】 / [A] / "A"： / 'A': / A  :
    escaped = re.escape(name)
    prefix_patterns = [
        rf'^[\s]*【{escaped}】[\s:：]*',         # 【A】 / 【A】：
        rf'^[\s]*\[{escaped}\][\s:：]*',         # [A] / [A]:
        rf'^[\s]*["\'"]{escaped}["\'"][\s:：]*', # "A"： / 'A':
        rf'^[\s]*{escaped}[\s]*[:：][\s]*',      # A： / A: / A  :
    ]
    # 反复剥除开头的前缀（可能 AI 连续输出多个前缀行）
    for _ in range(5):
        original = reply
        for pattern in prefix_patterns:
            reply = re.sub(pattern, '', reply, flags=re.MULTILINE)
        if reply == original:
            break

    # 3. 去除整条回复被引号包裹的情况（"xxx" 或 "xxx"）
    reply = reply.strip()
    if len(reply) >= 2:
        pairs = [('"', '"'), ('"', '"'), ("'", "'"), ("'", "'"), ('「', '」'), ('『', '』')]
        for left, right in pairs:
            if reply.startswith(left) and reply.endswith(right):
                reply = reply[len(left):-len(right)].strip()
                break

    # 4. 清理多余空行和首尾空白
    reply = re.sub(r'\n{3,}', '\n\n', reply).strip()
    return reply


async def get_ai_config(db: AsyncSession) -> AIConfig:
    result = await db.execute(select(AIConfig).where(AIConfig.id == 1))
    config = result.scalar_one_or_none()
    if not config:
        from app.config import AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_MAX_HISTORY, AI_PROVIDER
        config = AIConfig(
            id=1,
            provider=AI_PROVIDER,
            model=AI_MODEL,
            api_key=AI_API_KEY,
            base_url=AI_BASE_URL,
            max_history=AI_MAX_HISTORY,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


async def get_history(
    db: AsyncSession, persona_id: int, wx_user_id: str, limit: int
) -> list[dict]:
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.persona_id == persona_id,
            Conversation.wx_user_id == wx_user_id,
        )
        .order_by(Conversation.id.desc())
        .limit(limit)
    )
    rows = list(reversed(result.scalars().all()))
    return [{"role": r.role, "content": r.content} for r in rows]


async def chat_with_persona(
    db: AsyncSession,
    persona: Persona,
    user_message: str,
    wx_user_id: str = "",
) -> str:
    config = await get_ai_config(db)
    history = await get_history(db, persona.id, wx_user_id, config.max_history)

    messages = [
        {"role": "system", "content": persona.system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]

    reply = await chat_completion(config, messages)
    reply = _sanitize_reply(reply, persona.name)

    # 存储用户消息和 AI 回复
    db.add(Conversation(persona_id=persona.id, role="user", content=user_message, wx_user_id=wx_user_id))
    db.add(Conversation(persona_id=persona.id, role="assistant", content=reply, wx_user_id=wx_user_id))
    await db.commit()

    return reply
