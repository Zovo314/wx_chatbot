import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# 企业微信
WX_CORPID = os.getenv("WX_CORPID", "")
WX_CORPSECRET = os.getenv("WX_CORPSECRET", "")
WX_TOKEN = os.getenv("WX_TOKEN", "")
WX_ENCODING_AES_KEY = os.getenv("WX_ENCODING_AES_KEY", "")
WX_AGENTID = int(os.getenv("WX_AGENTID", "0"))

# 微信客服
WX_KF_SECRET = os.getenv("WX_KF_SECRET", "")

# AI
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o")
AI_MAX_HISTORY = int(os.getenv("AI_MAX_HISTORY", "20"))

# 服务
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# 数据库
DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'ex.db'}"
