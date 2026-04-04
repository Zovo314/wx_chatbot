"""企业微信回调路由。"""

import asyncio
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, Request, Query, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import WX_CORPID, WX_CORPSECRET, WX_TOKEN, WX_ENCODING_AES_KEY, WX_AGENTID
from app.database import get_db, async_session
from app.models import Persona
from app.services.wx_crypto import WXBizMsgCrypt, parse_wx_msg
from app.services.chat import chat_with_persona

router = APIRouter(prefix="/wx", tags=["wechat"])

_crypto = None
_access_token_cache = {"token": "", "expires_at": 0}

# 每个用户当前激活的人格 slug
_active_persona: dict[str, str] = {}


def get_crypto() -> WXBizMsgCrypt:
    global _crypto
    if _crypto is None:
        _crypto = WXBizMsgCrypt(WX_TOKEN, WX_ENCODING_AES_KEY, WX_CORPID)
    return _crypto


async def get_access_token() -> str:
    import time
    now = time.time()
    if _access_token_cache["token"] and _access_token_cache["expires_at"] > now + 60:
        return _access_token_cache["token"]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": WX_CORPID, "corpsecret": WX_CORPSECRET},
        )
        data = resp.json()
        _access_token_cache["token"] = data["access_token"]
        _access_token_cache["expires_at"] = now + data.get("expires_in", 7200)
        return data["access_token"]


async def send_wx_message(user_id: str, content: str):
    token = await get_access_token()
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}",
            json={
                "touser": user_id,
                "msgtype": "text",
                "agentid": WX_AGENTID,
                "text": {"content": content},
            },
        )


@router.get("/callback")
async def verify_url(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """企业微信 URL 验证回调。"""
    crypto = get_crypto()
    reply = crypto.verify_url(msg_signature, timestamp, nonce, echostr)
    return int(reply)


@router.post("/callback")
async def receive_message(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    """接收企业微信消息（应用消息 + 客服消息通知），异步处理后主动回复。"""
    body = await request.body()
    crypto = get_crypto()
    decrypted_xml = crypto.decrypt_msg(msg_signature, timestamp, nonce, body.decode("utf-8"))
    msg = parse_wx_msg(decrypted_xml)

    print(f"[回调] msg_type={msg['msg_type']} event={msg.get('event','')} from={msg.get('from_user','')}")

    # 客服消息通知（event 类型，MsgType=event, Event=kf_msg_or_event）
    if msg["msg_type"] == "event":
        from app.services.kf import _handle_kf_event
        asyncio.create_task(_handle_kf_event(msg))
        return ""

    if msg["msg_type"] != "text":
        return ""

    user_id = msg["from_user"]
    content = msg["content"].strip()

    # 异步处理，立即返回空响应（企业微信 5 秒超时）
    asyncio.create_task(_handle_message(user_id, content))
    return ""


async def _handle_message(user_id: str, content: str):
    async with async_session() as db:
        # 特殊指令
        if content == "#列表":
            result = await db.execute(select(Persona))
            personas = result.scalars().all()
            if not personas:
                await send_wx_message(user_id, "还没有创建任何人格。请在 Web 后台创建。")
                return
            lines = ["当前人格列表："]
            for p in personas:
                active = " (当前)" if _active_persona.get(user_id) == p.slug else ""
                lines.append(f"  #{p.slug} — {p.name}{active}")
            lines.append("\n发送 #代号 切换人格")
            await send_wx_message(user_id, "\n".join(lines))
            return

        if content.startswith("#") and len(content) > 1:
            slug = content[1:]
            result = await db.execute(select(Persona).where(Persona.slug == slug))
            persona = result.scalar_one_or_none()
            if persona:
                _active_persona[user_id] = slug
                await send_wx_message(user_id, f"已切换到「{persona.name}」")
                return
            else:
                await send_wx_message(user_id, f"没有找到人格「{slug}」，发送 #列表 查看所有人格")
                return

        # 普通对话
        slug = _active_persona.get(user_id)
        if not slug:
            # 默认使用第一个人格
            result = await db.execute(select(Persona).limit(1))
            persona = result.scalar_one_or_none()
            if persona:
                _active_persona[user_id] = persona.slug
            else:
                await send_wx_message(user_id, "还没有创建任何人格。请在 Web 后台创建。")
                return
        else:
            result = await db.execute(select(Persona).where(Persona.slug == slug))
            persona = result.scalar_one_or_none()
            if not persona:
                await send_wx_message(user_id, "当前人格不存在，发送 #列表 重新选择")
                return

        try:
            reply = await chat_with_persona(db, persona, content, wx_user_id=user_id)
            await send_wx_message(user_id, reply)
        except Exception as e:
            print(f"[企微] AI调用出错: {e}")
            await send_wx_message(user_id, "抱歉，处理消息时出错了，请稍后重试。")
