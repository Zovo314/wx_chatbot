"""pytest 全局夹具。所有测试使用内存 SQLite，不碰生产库。"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # 触发 models.py 里所有模型注册到 metadata
    import app.models  # noqa: F401
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest.fixture(autouse=True)
def _disable_scheduler(monkeypatch):
    """测试中禁止真正的 APScheduler 启动，避免 TestClient 里后台线程干扰。
    Task 4 前 scheduler 模块还不存在，这里做 try/except 兜底。"""
    try:
        from app.services import scheduler as sch
        monkeypatch.setattr(sch, "start_scheduler", lambda: None, raising=False)
        monkeypatch.setattr(sch, "stop_scheduler", lambda: None, raising=False)
    except ImportError:
        pass
