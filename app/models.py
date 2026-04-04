from datetime import datetime, timezone
from sqlalchemy import Integer, Text, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def now_utc():
    return datetime.now(timezone.utc)


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    memory: Mapped[str] = mapped_column(Text, default="")
    persona: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    wx_user_id: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class AIConfig(Base):
    __tablename__ = "ai_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), default="openai")
    model: Mapped[str] = mapped_column(String(100), default="gpt-4o")
    api_key: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(Text, default="https://api.openai.com/v1")
    max_history: Mapped[int] = mapped_column(Integer, default=20)
