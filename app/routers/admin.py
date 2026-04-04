"""Web 后台路由：人格管理 + AI 配置。"""

import json
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_DIR
from app.database import get_db
from app.models import Persona, AIConfig
from app.services.chat import get_ai_config
from app.services.persona_gen import generate_memory, generate_persona, build_system_prompt

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

TOOLS_DIR = BASE_DIR / "tools"


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Persona).order_by(Persona.id.desc()))
    personas = result.scalars().all()
    return templates.TemplateResponse("index.html", {"request": request, "personas": personas})


@router.get("/create", response_class=HTMLResponse)
async def create_page(request: Request):
    return templates.TemplateResponse("create.html", {"request": request})


@router.post("/create")
async def create_persona(
    request: Request,
    slug: str = Form(...),
    name: str = Form(...),
    basic_info: str = Form(""),
    personality: str = Form(""),
    raw_text: str = Form(""),
    chat_file: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    # 检查 slug 是否重复
    existing = await db.execute(select(Persona).where(Persona.slug == slug))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse("create.html", {
            "request": request,
            "error": f"代号「{slug}」已存在",
            "slug": slug, "name": name, "basic_info": basic_info,
            "personality": personality, "raw_text": raw_text,
        })

    # 处理上传的聊天记录文件
    file_analysis = ""
    if chat_file and chat_file.filename:
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
            result = subprocess.run(
                ["python3", str(parser), "--file", tmp_path, "--target", name, "--output", out_path],
                capture_output=True, text=True, timeout=30,
            )
            if Path(out_path).exists():
                file_analysis = Path(out_path).read_text(encoding="utf-8")
                Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    raw_material = ""
    if file_analysis:
        raw_material += f"### 聊天记录分析\n{file_analysis}\n\n"
    if raw_text:
        raw_material += f"### 用户口述\n{raw_text}\n"

    config = await get_ai_config(db)

    # 并发生成 memory 和 persona
    import asyncio
    memory_task = generate_memory(config, name, basic_info, personality, raw_material)
    persona_task = generate_persona(config, name, basic_info, personality, raw_material)
    memory, persona_text = await asyncio.gather(memory_task, persona_task)

    system_prompt = build_system_prompt(name, memory, persona_text)

    meta = {
        "name": name,
        "slug": slug,
        "profile": {"basic_info": basic_info, "personality": personality},
    }

    p = Persona(
        slug=slug,
        name=name,
        memory=memory,
        persona=persona_text,
        system_prompt=system_prompt,
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    db.add(p)
    await db.commit()

    return RedirectResponse(url=f"/admin/detail/{slug}", status_code=303)


@router.get("/detail/{slug}", response_class=HTMLResponse)
async def detail_page(request: Request, slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    persona = result.scalar_one_or_none()
    if not persona:
        return RedirectResponse(url="/admin/")
    return templates.TemplateResponse("detail.html", {"request": request, "persona": persona})


@router.post("/detail/{slug}/edit")
async def edit_persona(
    slug: str,
    memory: str = Form(""),
    persona_text: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    p = result.scalar_one_or_none()
    if not p:
        return RedirectResponse(url="/admin/")
    p.memory = memory
    p.persona = persona_text
    p.system_prompt = build_system_prompt(p.name, memory, persona_text)
    await db.commit()
    return RedirectResponse(url=f"/admin/detail/{slug}", status_code=303)


@router.post("/detail/{slug}/delete")
async def delete_persona(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    p = result.scalar_one_or_none()
    if p:
        await db.delete(p)
        await db.commit()
    return RedirectResponse(url="/admin/", status_code=303)


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, db: AsyncSession = Depends(get_db)):
    config = await get_ai_config(db)
    return templates.TemplateResponse("config.html", {"request": request, "config": config})


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


@router.get("/kf", response_class=HTMLResponse)
async def kf_page(request: Request, db: AsyncSession = Depends(get_db)):
    from app.services.kf import get_kf_persona_map
    result = await db.execute(select(Persona).order_by(Persona.id.desc()))
    personas = result.scalars().all()
    kf_map = get_kf_persona_map()
    return templates.TemplateResponse("kf.html", {
        "request": request, "personas": personas, "kf_map": kf_map,
    })


@router.post("/kf/create")
async def kf_create(
    request: Request,
    slug: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.services.kf import create_kf_account, get_kf_account_link, bind_kf_persona
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    persona = result.scalar_one_or_none()
    if not persona:
        return RedirectResponse(url="/admin/kf", status_code=303)

    try:
        kf = await create_kf_account(f"{persona.name}")
        open_kfid = kf["open_kfid"]
        link = await get_kf_account_link(open_kfid)
        bind_kf_persona(open_kfid, slug)

        # 保存 kf 信息到 persona 的 meta_json
        meta = json.loads(persona.meta_json) if persona.meta_json else {}
        meta["kf"] = {"open_kfid": open_kfid, "link": link}
        persona.meta_json = json.dumps(meta, ensure_ascii=False)
        await db.commit()

        return RedirectResponse(url="/admin/kf", status_code=303)
    except Exception as e:
        result = await db.execute(select(Persona).order_by(Persona.id.desc()))
        personas = result.scalars().all()
        from app.services.kf import get_kf_persona_map
        return templates.TemplateResponse("kf.html", {
            "request": request, "personas": personas,
            "kf_map": get_kf_persona_map(), "error": str(e),
        })
