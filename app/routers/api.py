"""API 路由：提供给前端 AJAX 或未来扩展使用。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Persona, Conversation
from app.services.chat import chat_with_persona

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/personas")
async def list_personas(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Persona).order_by(Persona.id.desc()))
    personas = result.scalars().all()
    return [{"id": p.id, "slug": p.slug, "name": p.name} for p in personas]


@router.post("/chat/{slug}")
async def chat(slug: str, message: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Persona).where(Persona.slug == slug))
    persona = result.scalar_one_or_none()
    if not persona:
        return {"error": "人格不存在"}
    reply = await chat_with_persona(db, persona, message, wx_user_id="web")
    return {"reply": reply}
