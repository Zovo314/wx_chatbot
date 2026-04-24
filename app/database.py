from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    from app.models import Persona, Conversation, AIConfig, PersonaSchedule  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ---- 自动迁移：v2 新增 persona_type 列 ----
        # 幂等：列已存在则跳过；存量数据默认 'private'
        try:
            rows = await conn.execute(text("PRAGMA table_info(personas)"))
            cols = [r[1] for r in rows.fetchall()]
            if "persona_type" not in cols:
                await conn.execute(text(
                    "ALTER TABLE personas ADD COLUMN persona_type "
                    "VARCHAR(20) NOT NULL DEFAULT 'private'"
                ))
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_personas_persona_type "
                    "ON personas(persona_type)"
                ))
                print("[migrate] 已添加 persona_type 列，存量数据默认 private")
        except Exception as e:  # noqa: BLE001
            # 非 SQLite 或迁移失败不阻塞主服务
            print(f"[migrate] 迁移检查跳过: {e}")


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
