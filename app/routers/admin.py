"""Web 后台路由 v2：人格管理 + AI 配置 + 双 Pipeline 路由。

变更（相对 v1）：
1. 创建表单接收 persona_type（private / public / fictional）
2. 不同类型走不同的 Pipeline（persona_v2.generate_persona_v2）
3. 新增维度增量重生成接口 /detail/{slug}/regen/{dimension}
4. meta_json 写入 dimensions / quality_warnings / persona_type
"""

import json
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_DIR
from app.database import get_db
from app.models import Persona, PERSONA_TYPES
from app.services.chat import get_ai_config
from app.services.persona_v2 import (
    PersonaPayload,
    generate_persona_v2,
    regenerate_dimension,
)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

TOOLS_DIR = BASE_DIR / "tools"


# -------- 列表 --------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Persona).order_by(Persona.id.desc()))
    personas = result.scalars().all()
    return templates.TemplateResponse(
        request, name="index.html", context={"personas": personas}
    )


# -------- 创建：第一步选择类型 --------
@router.get("/create", response_class=HTMLResponse)
async def create_choose_type(request: Request):
    """显示类型选择卡片。"""
    return templates.TemplateResponse(request, name="create_type.html")


@router.get("/create/{persona_type}", response_class=HTMLResponse)
async def create_form(request: Request, persona_type: str):
    """根据类型显示对应的表单。"""
    if persona_type not in PERSONA_TYPES:
        return RedirectResponse(url="/admin/create", status_code=303)
    template = "create_private.html" if persona_type == "private" else "create_non_private.html"
    return templates.TemplateResponse(
        request, name=template, context={"persona_type": persona_type}
    )


# -------- 向后兼容：v1 旧接口 POST /admin/create --------
# 老的浏览器收藏 / 旧表单提交会落到这里，统一按 private 处理。
@router.post("/create")
async def create_legacy(
    request: Request,
    slug: str = Form(...),
    name: str = Form(...),
    basic_info: str = Form(""),
    personality: str = Form(""),
    raw_text: str = Form(""),
    chat_file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    """v1 兼容入口：转发到 private 创建。"""
    return await _create_persona_common(
        request=request, db=db,
        persona_type="private",
        slug=slug, name=name,
        basic_info=basic_info, personality=personality,
        relationship_context="",
        raw_text=raw_text, chat_file=chat_file,
        domain="", works="",
    )


# -------- 创建：private 提交 --------
@router.post("/create/private")
async def create_private(
    request: Request,
    slug: str = Form(...),
    name: str = Form(...),
    basic_info: str = Form(""),
    personality: str = Form(""),
    relationship_context: str = Form(""),
    raw_text: str = Form(""),
    chat_file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    return await _create_persona_common(
        request=request, db=db,
        persona_type="private",
        slug=slug, name=name,
        basic_info=basic_info, personality=personality,
        relationship_context=relationship_context,
        raw_text=raw_text, chat_file=chat_file,
        domain="", works="",
    )


# -------- 创建：non_private（public/fictional）提交 --------
@router.post("/create/non_private")
async def create_non_private(
    request: Request,
    persona_type: str = Form(...),    # public 或 fictional
    slug: str = Form(...),
    name: str = Form(...),
    basic_info: str = Form(""),
    personality: str = Form(""),
    domain: str = Form(""),
    works: str = Form(""),
    raw_text: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if persona_type not in ("public", "fictional"):
        raise HTTPException(400, "非法的 persona_type")
    return await _create_persona_common(
        request=request, db=db,
        persona_type=persona_type,
        slug=slug, name=name,
        basic_info=basic_info, personality=personality,
        relationship_context="",
        raw_text=raw_text, chat_file=None,
        domain=domain, works=works,
    )


async def _create_persona_common(
    request: Request,
    db: AsyncSession,
    persona_type: str,
    slug: str,
    name: str,
    basic_info: str,
    personality: str,
    relationship_context: str,
    raw_text: str,
    chat_file: UploadFile | None,
    domain: str,
    works: str,
):
    # 1. slug 唯一性
    existing = await db.execute(select(Persona).where(Persona.slug == slug))
    if existing.scalar_one_or_none():
        template_name = "create_private.html" if persona_type == "private" else "create_non_private.html"
        return templates.TemplateResponse(
            request, name=template_name,
            context={
                "error": f"代号「{slug}」已存在",
                "persona_type": persona_type,
                "slug": slug, "name": name,
                "basic_info": basic_info, "personality": personality,
                "relationship_context": relationship_context,
                "domain": domain, "works": works, "raw_text": raw_text,
            },
        )

    # 2. 解析聊天记录文件（仅 private）
    file_analysis = ""
    if persona_type == "private" and chat_file and chat_file.filename:
        file_analysis = await _parse_chat_file(chat_file, name)

    raw_material = ""
    if file_analysis:
        raw_material += f"### 聊天记录分析\n{file_analysis}\n\n"
    if raw_text:
        raw_material += f"### 用户口述\n{raw_text}\n"

    # 3. 构造 payload 调用 v2
    payload = PersonaPayload(
        name=name,
        persona_type=persona_type,
        basic_info=basic_info,
        personality=personality,
        relationship_context=relationship_context,
        domain=domain,
        works=works,
        raw_material=raw_material,
    )

    # ASK 模式拦截：信息严重不足直接返回引导问卷
    if payload.mode == "ASK":
        template_name = "create_private.html" if persona_type == "private" else "create_non_private.html"
        return templates.TemplateResponse(
            request, name=template_name,
            context={
                "error": "信息量不足以生成有质量的人格，请补全基本信息、性格画像或语料后再试。",
                "persona_type": persona_type,
                "slug": slug, "name": name,
                "basic_info": basic_info, "personality": personality,
                "relationship_context": relationship_context,
                "domain": domain, "works": works, "raw_text": raw_text,
                "ask_mode": True,
            },
        )

    config = await get_ai_config(db)
    result = await generate_persona_v2(config, payload)

    # 4. 写入 DB
    meta = {
        "name": name,
        "slug": slug,
        "persona_type": persona_type,
        "mode": result["mode"],
        "profile": {
            "basic_info": basic_info,
            "personality": personality,
            "relationship_context": relationship_context,
            "domain": domain,
            "works": works,
        },
        "dimensions": result["dimensions"],
        "quality_warnings": result["quality_warnings"],
    }

    p = Persona(
        slug=slug,
        name=name,
        persona_type=persona_type,
        memory=result["memory"],
        persona=result["persona"],
        system_prompt=result["system_prompt"],
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    db.add(p)
    await db.commit()

    return RedirectResponse(url=f"/admin/detail/{slug}", status_code=303)


# -------- 聊天记录解析（沿用 v1） --------
async def _parse_chat_file(chat_file: UploadFile, name: str) -> str:
    content_bytes = await chat_file.read()
    suffix = Path(chat_file.filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb") as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name
    try:
        out_path = tempfile.mktemp(suffix=".txt")
        parser = TOOLS_DIR / "wechat_parser.py"
        if suffix.lower() in (".mht",):
            parser = TOOLS_DIR / "qq_parser.py"
        subprocess.run(
            ["python3", str(parser), "--file", tmp_path,
             "--target", name, "--output", out_path],
            capture_output=True, text=True, timeout=30,
        )
        if Path(out_path).exists():
            txt = Path(out_path).read_text(encoding="utf-8")
            Path(out_path).unlink(missing_ok=True)
            return txt
    except Exception:  # noqa: BLE001
        pass
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return ""


# -------- 详情 --------
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


# -------- 手动编辑（保留 v1） --------
@router.post("/detail/{slug}/edit")
async def edit_persona(
    slug: str,
    memory: str = Form(""),
    persona_text: str = Form(""),
    system_prompt: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    p = result.scalar_one_or_none()
    if not p:
        return RedirectResponse(url="/admin/")
    p.memory = memory
    p.persona = persona_text
    if system_prompt:
        p.system_prompt = system_prompt
    await db.commit()
    return RedirectResponse(url=f"/admin/detail/{slug}", status_code=303)


# -------- 增量重生成单个维度 --------
@router.post("/detail/{slug}/regen/{dimension}")
async def regen_dimension(
    slug: str,
    dimension: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "persona not found")

    meta = json.loads(p.meta_json) if p.meta_json else {}
    profile = meta.get("profile", {})

    payload = PersonaPayload(
        name=p.name,
        persona_type=p.persona_type,
        basic_info=profile.get("basic_info", ""),
        personality=profile.get("personality", ""),
        relationship_context=profile.get("relationship_context", ""),
        domain=profile.get("domain", ""),
        works=profile.get("works", ""),
        raw_material="",  # 增量更新不重新解析语料
    )

    config = await get_ai_config(db)
    res = await regenerate_dimension(config, payload, dimension)
    if not res.ok:
        return JSONResponse({"ok": False, "error": res.error}, status_code=400)

    # 更新 meta_json.dimensions[dimension]
    meta.setdefault("dimensions", {})[dimension] = res.data
    p.meta_json = json.dumps(meta, ensure_ascii=False)
    await db.commit()

    return JSONResponse({"ok": True, "dimension": dimension, "data": res.data})


# -------- 删除 --------
@router.post("/detail/{slug}/delete")
async def delete_persona(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    p = result.scalar_one_or_none()
    if p:
        await db.delete(p)
        await db.commit()
    return RedirectResponse(url="/admin/", status_code=303)


# -------- AI 配置（沿用 v1） --------
@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, db: AsyncSession = Depends(get_db)):
    config = await get_ai_config(db)
    return templates.TemplateResponse(
        request, name="config.html", context={"config": config}
    )


@router.post("/config")
async def save_config(
    provider: str = Form("openai"),
    model: str = Form("gpt-4o"),
    api_key: str = Form(""),
    base_url: str = Form("https://api.openai.com/v1"),
    max_history: int = Form(20),
    db: AsyncSession = Depends(get_db),
):
    config = await get_ai_config(db)
    config.provider = provider
    config.model = model
    if api_key:
        config.api_key = api_key
    config.base_url = base_url
    config.max_history = max_history
    await db.commit()
    return RedirectResponse(url="/admin/config", status_code=303)


# -------- 微信客服（沿用 v1） --------
@router.get("/kf", response_class=HTMLResponse)
async def kf_page(request: Request, db: AsyncSession = Depends(get_db)):
    from app.services.kf import get_kf_persona_map, list_kf_accounts
    result = await db.execute(select(Persona).order_by(Persona.id.desc()))
    personas = result.scalars().all()
    kf_map = get_kf_persona_map()
    try:
        kf_accounts = await list_kf_accounts()
    except Exception:  # noqa: BLE001
        kf_accounts = []
    return templates.TemplateResponse(
        request, name="kf.html",
        context={"personas": personas, "kf_map": kf_map, "kf_accounts": kf_accounts},
    )


@router.post("/kf/create")
async def kf_create(
    request: Request,
    slug: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.services.kf import (
        create_kf_account, get_kf_account_link, bind_kf_persona,
        get_kf_persona_map,
    )
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    persona = result.scalar_one_or_none()
    if not persona:
        return RedirectResponse(url="/admin/kf", status_code=303)

    try:
        kf = await create_kf_account(f"{persona.name}")
        open_kfid = kf["open_kfid"]
        link = await get_kf_account_link(open_kfid)
        bind_kf_persona(open_kfid, slug)

        meta = json.loads(persona.meta_json) if persona.meta_json else {}
        meta["kf"] = {"open_kfid": open_kfid, "link": link}
        persona.meta_json = json.dumps(meta, ensure_ascii=False)
        await db.commit()
        return RedirectResponse(url="/admin/kf", status_code=303)
    except Exception as e:  # noqa: BLE001
        result = await db.execute(select(Persona).order_by(Persona.id.desc()))
        personas = result.scalars().all()
        return templates.TemplateResponse(
            request, name="kf.html",
            context={
                "personas": personas, "kf_accounts": [],
                "kf_map": get_kf_persona_map(), "error": str(e),
            },
        )


@router.post("/kf/bind")
async def kf_bind(
    request: Request,
    open_kfid: str = Form(...),
    slug: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.services.kf import bind_kf_persona
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    persona = result.scalar_one_or_none()
    if not persona:
        return RedirectResponse(url="/admin/kf", status_code=303)

    meta = json.loads(persona.meta_json) if persona.meta_json else {}
    meta["kf"] = {"open_kfid": open_kfid, "link": ""}
    persona.meta_json = json.dumps(meta, ensure_ascii=False)
    await db.commit()
    bind_kf_persona(open_kfid, slug)
    return RedirectResponse(url="/admin/kf", status_code=303)


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
