from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pathlib import Path

from app.database import init_db
from app.routers import admin, api, wechat


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # 客服模块失败不应阻塞主服务启动
    try:
        await _restore_kf_bindings()
        await _drain_kf_history()
    except Exception as e:
        print(f"[启动] 客服模块初始化失败（忽略，主服务继续）: {e}")
    yield


async def _restore_kf_bindings():
    import json
    from app.database import async_session
    from app.models import Persona
    from app.services.kf import bind_kf_persona
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(Persona))
        for p in result.scalars().all():
            try:
                meta = json.loads(p.meta_json) if p.meta_json else {}
                kf_info = meta.get("kf", {})
                if kf_info.get("open_kfid"):
                    bind_kf_persona(kf_info["open_kfid"], p.slug)
            except Exception:
                pass


async def _drain_kf_history():
    """启动时跳过所有历史客服消息，避免重复处理。

    客服功能是可选的，任何失败（如 Secret 未配置、企业未开通客服模块）
    都只打印警告，不应阻塞主服务启动。
    """
    from app.services.kf import sync_kf_messages, get_kf_persona_map
    for open_kfid in get_kf_persona_map():
        try:
            while True:
                msgs = await sync_kf_messages(open_kfid)
                if not msgs:
                    break
            print(f"[启动] 已跳过 {open_kfid} 的历史消息")
        except Exception as e:
            print(f"[启动] 跳过客服 {open_kfid} 历史消息失败（忽略）: {e}")


app = FastAPI(title="AI人格复刻", lifespan=lifespan)

static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(admin.router)
app.include_router(api.router)
app.include_router(wechat.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/admin/")
