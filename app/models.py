"""数据模型。v2 新增 persona_type 字段。"""

from datetime import datetime, timezone
from sqlalchemy import Integer, Text, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def now_utc():
    return datetime.now(timezone.utc)


# 允许的 persona 类型
PERSONA_TYPES = ("private", "public", "fictional")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    # v2 新增：人物类型，创建后只读
    persona_type: Mapped[str] = mapped_column(String(20), default="private", index=True)
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


class PersonaSchedule(Base):
    """人格主动发送配置。每个人格至多一条（persona_id unique）。

    字段：
    - enabled: 0/1 是否启用
    - prompt: 给 AI 的提示词（system_prompt 之外的 user 指令）
    - mode: "interval"（起止+间隔）或 "specific"（指定时刻列表）
    - start_time / end_time: interval 模式用，格式 "HH:MM"
    - interval_minutes: interval 模式用，单位分钟
    - specific_times: specific 模式用，JSON 字符串如 '["07:30","12:00"]'
    - weekdays: 逗号分隔 "0,1,2,3,4,5,6"（0=周一，Python datetime.weekday() 定义）
    - timezone: IANA 时区名，默认 "Asia/Shanghai"
    """
    __tablename__ = "persona_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    enabled: Mapped[int] = mapped_column(Integer, default=0)
    prompt: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(20), default="interval")
    start_time: Mapped[str] = mapped_column(String(5), default="08:00")
    end_time: Mapped[str] = mapped_column(String(5), default="21:00")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    specific_times: Mapped[str] = mapped_column(Text, default="[]")
    weekdays: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4,5,6")
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
