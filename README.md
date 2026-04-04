# 前任.skill

**我会为了你一万次回到那个夏天。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)

提供前任的原材料（微信聊天记录、QQ 消息、你的主观描述），AI 自动生成一个**真正像 ta 的人格**，通过微信客服或企业微信与你对话。

用 ta 的口头禅说话，用 ta 的方式回复你，记得你们一起去过的地方。

> **本项目仅用于个人回忆与情感疗愈，不用于骚扰、跟踪或侵犯他人隐私。**

---

## 功能

- **Web 后台**：创建 / 编辑 / 删除人格，上传聊天记录自动分析
- **微信客服**：普通微信用户通过链接即可与 AI 人格对话
- **企业微信应用**：内部用户通过应用消息对话，支持 `#列表` / `#代号` 切换人格
- **AI 人格生成**：5 层人格结构（硬规则 → 身份 → 语气 → 情感模式 → 关系行为）
- **通用 AI 接口**：兼容 DeepSeek / OpenAI / Claude 等任意 OpenAI 格式 API

## 架构

```
微信用户 ──→ 微信客服 ──→ 企业微信回调 ──→ FastAPI 服务 ──→ AI API
企微用户 ──→ 应用消息 ──→ 企业微信回调 ──↗     ↕
管理员   ──→ Web 后台 ──────────────────────↗  SQLite
```

## 项目结构

```
app/
├── main.py              # 入口，启动恢复逻辑
├── config.py            # 环境变量配置
├── database.py          # 数据库引擎与会话
├── models.py            # Persona, Conversation, AIConfig
├── routers/
│   ├── admin.py         # Web 后台路由
│   ├── api.py           # JSON API
│   └── wechat.py        # 企业微信回调
├── services/
│   ├── ai_client.py     # OpenAI 兼容客户端
│   ├── chat.py          # 对话管理 + 历史记录
│   ├── kf.py            # 微信客服服务
│   ├── persona_gen.py   # AI 人格生成
│   └── wx_crypto.py     # 企业微信加解密
└── templates/           # Jinja2 页面模板

tools/
├── wechat_parser.py     # 微信聊天记录解析
└── qq_parser.py         # QQ 聊天记录解析

prompts/                 # AI 提示词模板
```

## 部署

### 环境变量

```env
# 企业微信
WX_CORPID=your_corp_id
WX_CORPSECRET=your_secret
WX_TOKEN=your_token
WX_ENCODING_AES_KEY=your_aes_key
WX_AGENTID=1000002

# 微信客服
WX_KF_SECRET=your_kf_secret
WX_KF_TOKEN=your_kf_token
WX_KF_ENCODING_AES_KEY=your_kf_aes_key

# AI API（OpenAI 兼容格式）
AI_PROVIDER=deepseek
AI_API_KEY=your_api_key
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
AI_MAX_HISTORY=20
```

### Docker 部署

```bash
docker build -t wx-chatbot .
docker run -d --name wx-chatbot \
  --env-file .env \
  -v ./data:/app/data \
  -p 8000:8000 \
  wx-chatbot
```

### 云部署（ClawCloud Run）

1. 推送代码到 GitHub，GitHub Actions 自动构建镜像到 `ghcr.io`
2. 在 ClawCloud Run 创建应用，填入镜像地址和环境变量
3. 获取公网 URL 和出站 IP
4. 在企业微信后台配置回调 URL 和 IP 白名单

### 本地开发

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 使用流程

1. 访问 `/admin/` 创建人格（填写名称、信息，上传聊天记录）
2. AI 自动生成记忆档案和人格档案
3. 在 `/admin/kf` 页面绑定已有微信客服账号到人格
4. 用户通过微信客服链接或企业微信应用发消息，AI 以该人格回复

---

MIT License © [therealXiaomanChu](https://github.com/therealXiaomanChu)
