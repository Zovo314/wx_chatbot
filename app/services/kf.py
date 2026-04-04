"""微信客服服务。

微信客服的消息流程与应用消息不同：
1. 回调只通知"有新消息"（event_type=kf_msg_or_event）
2. 需要主动调 sync_msg 接口拉取消息内容
3. 通过 send_msg 接口回复
"""

import time

import httpx
from sqlalchemy import select

from app.config import WX_CORPID, WX_KF_SECRET
from app.database import async_session
from app.models import Persona
from app.services.chat import chat_with_persona

_kf_token_cache = {"token": "", "expires_at": 0}
_kf_cursor: dict[str, str] = {}  # 每个客服账号的消息游标

# 客服账号 → 人格 slug 的绑定
_kf_persona_map: dict[str, str] = {}


async def get_kf_access_token() -> str:
    now = time.time()
    if _kf_token_cache["token"] and _kf_token_cache["expires_at"] > now + 60:
        return _kf_token_cache["token"]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": WX_CORPID, "corpsecret": WX_KF_SECRET},
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise Exception(f"获取客服token失败: {data}")
        _kf_token_cache["token"] = data["access_token"]
        _kf_token_cache["expires_at"] = now + data.get("expires_in", 7200)
        return data["access_token"]


async def create_kf_account(name: str, media_id: str = "") -> dict:
    """创建客服账号。返回 {open_kfid, url}"""
    token = await get_kf_access_token()
    payload = {"name": name}
    if media_id:
        payload["media_id"] = media_id
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/account/add?access_token={token}",
            json=payload,
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise Exception(f"创建客服账号失败: {data}")
        return {"open_kfid": data["open_kfid"]}


async def get_kf_account_link(open_kfid: str, scene: str = "persona") -> str:
    """获取客服账号的客服链接（用户点击后可发起对话）。"""
    token = await get_kf_access_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/add_contact_way?access_token={token}",
            json={"open_kfid": open_kfid, "scene": scene},
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise Exception(f"获取客服链接失败: {data}")
        return data.get("url", "")


async def sync_kf_messages(open_kfid: str) -> list[dict]:
    """拉取客服消息。"""
    token = await get_kf_access_token()
    cursor = _kf_cursor.get(open_kfid, "")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={token}",
            json={"cursor": cursor, "open_kfid": open_kfid, "limit": 100},
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            return []
        if data.get("next_cursor"):
            _kf_cursor[open_kfid] = data["next_cursor"]
        return data.get("msg_list", [])


async def ensure_session_ready(open_kfid: str, external_userid: str):
    """确保会话状态允许 API 发消息。

    状态说明：
    0 = 新接入待处理（可发消息）
    1 = 待接入池（可发消息）
    2 = 企业接待池（可发消息）
    3 = 人工接待中（不可 API 发消息，需转接）
    4 = 智能助手接待（不可 API 发消息）
    """
    token = await get_kf_access_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/get?access_token={token}",
            json={"open_kfid": open_kfid, "external_userid": external_userid},
        )
        data = resp.json()
        state = data.get("service_state", -1)
        servicer = data.get("servicer_userid", "")

        # 状态 0/1/2 可以直接发消息
        if state in (0, 1, 2):
            return

        # 状态 3(人工) 或 4(智能助手)，需要结束当前接待再转回
        if state in (3, 4):
            trans_payload = {
                "open_kfid": open_kfid,
                "external_userid": external_userid,
                "service_state": 0,
            }
            if state == 3 and servicer:
                trans_payload["servicer_userid"] = servicer
            resp2 = await client.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans?access_token={token}",
                json=trans_payload,
            )
            print(f"转接会话状态: {state} → 0, result={resp2.json()}")


async def send_kf_message(open_kfid: str, external_userid: str, content: str):
    """给客户发消息。先确保会话状态正确。"""
    if not content or not content.strip():
        print("跳过发送：内容为空")
        return

    await ensure_session_ready(open_kfid, external_userid)

    token = await get_kf_access_token()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token={token}",
            json={
                "touser": external_userid,
                "open_kfid": open_kfid,
                "msgtype": "text",
                "text": {"content": content},
            },
        )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            print(f"发送客服消息失败: {data}")


async def _handle_kf_event(msg: dict):
    """处理客服事件：拉取消息 → 匹配人格 → AI 回复。"""
    try:
        async with async_session() as db:
            # 只拉取有绑定的客服账号
            kf_ids = list(_kf_persona_map.keys())
            if not kf_ids:
                # 没有绑定则拉取所有
                token = await get_kf_access_token()
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://qyapi.weixin.qq.com/cgi-bin/kf/account/list?access_token={token}",
                    )
                    data = resp.json()
                    kf_ids = [kf["open_kfid"] for kf in data.get("account_list", [])]

            for open_kfid in kf_ids:
                messages = await sync_kf_messages(open_kfid)
                print(f"[客服] {open_kfid} 拉取到 {len(messages)} 条新消息")

                for m in messages:
                    if m.get("origin") != 3:  # 3=客户发送
                        continue
                    if m.get("msgtype") != "text":
                        continue

                    external_userid = m.get("external_userid", "")
                    content = m.get("text", {}).get("content", "").strip()
                    if not content or not external_userid:
                        continue

                    print(f"[客服] 收到消息: {content} from {external_userid}")

                    slug = _kf_persona_map.get(open_kfid)
                    if slug:
                        result = await db.execute(select(Persona).where(Persona.slug == slug))
                        persona = result.scalar_one_or_none()
                    else:
                        result = await db.execute(select(Persona).limit(1))
                        persona = result.scalar_one_or_none()

                    if not persona:
                        await send_kf_message(open_kfid, external_userid, "暂无可用人格，请联系管理员。")
                        continue

                    try:
                        reply = await chat_with_persona(db, persona, content, wx_user_id=f"kf_{external_userid}")
                        print(f"[客服] AI回复: {reply[:50]}")
                        await send_kf_message(open_kfid, external_userid, reply)
                    except Exception as e:
                        print(f"[客服] AI调用出错: {e}")
                        await send_kf_message(open_kfid, external_userid, "抱歉，处理消息时出错了，请稍后重试。")
    except Exception as e:
        print(f"[客服] _handle_kf_event 异常: {e}")
        import traceback
        traceback.print_exc()


def bind_kf_persona(open_kfid: str, slug: str):
    """绑定客服账号到指定人格。"""
    _kf_persona_map[open_kfid] = slug


def get_kf_persona_map() -> dict[str, str]:
    return dict(_kf_persona_map)
