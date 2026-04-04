# 前任.skill — 阶段性总结（Stage 1）

> 日期：2026-04-03

## 项目概述

将 [ex-skill](https://github.com/therealXiaomanChu/ex-skill)（一个生成前任 AI 人格的 Claude Code Skill）改造为面向用户的 Web 服务。用户通过 Web 后台上传聊天记录，AI 自动生成人格档案，然后通过企业微信应用或微信客服与 AI 人格对话。

## 已完成功能

### 核心架构
- **FastAPI 单服务**：SQLite + SQLAlchemy async，Jinja2 模板 + Tailwind CSS
- **AI 集成**：OpenAI 兼容接口，已对接 DeepSeek，支持任意兼容 API

### Web 后台（/admin）
- 人格 CRUD：创建、查看、编辑、删除
- 聊天记录解析：微信 / QQ 导出文件 → AI 自动生成记忆 + 人格档案
- AI 配置：在线修改模型、API Key、Base URL
- 微信客服管理：一键创建客服账号并绑定人格

### 企业微信应用消息
- 消息加解密回调（AES-256-CBC）
- 指令系统：`#列表` 查看人格、`#代号` 切换人格
- 异步消息处理（5 秒超时应对）

### 微信客服
- 客服消息拉取模型（sync_msg）
- 会话状态管理（0-4 状态自动转接）
- 启动时跳过历史消息，避免重复处理
- 空内容检测，防止发送失败

### AI 回复质量
- 5 层人格结构：硬规则 → 身份 → 语气 → 情感模式 → 关系行为
- 系统提示词组装：运行规则 + 记忆 + 人格
- 正则后处理：自动去除旁白 / 括号描写

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
│   └── wechat.py        # 企业微信回调（含客服事件转发）
├── services/
│   ├── ai_client.py     # OpenAI 兼容客户端
│   ├── chat.py          # 对话管理 + 历史记录
│   ├── kf.py            # 微信客服服务
│   ├── persona_gen.py   # AI 人格生成
│   └── wx_crypto.py     # 企业微信加解密
└── templates/           # Jinja2 模板（6 个页面）

tools/
├── wechat_parser.py     # 微信聊天记录解析
└── qq_parser.py         # QQ 聊天记录解析

prompts/                 # AI 提示词模板（7 个）
```

## 本次清理内容

1. **删除死代码**
   - `kf.py`：移除未使用的回调路由（`kf_verify_url`、`kf_receive_event`）、`get_kf_crypto`、`_kf_crypto`、`_kf_active_persona`
   - `wx_crypto.py`：移除未使用的 `encrypt_msg` 和 `_encrypt`
   - 清理对应的无用 import（`asyncio`、`time`、`socket`、`Request`、`Query`、`APIRouter`）

2. **模块重组**
   - `kf.py` 从 `routers/` 移至 `services/`（它不含路由，是纯服务层）
   - 更新所有引用路径（`main.py`、`admin.py`、`wechat.py`）
   - 从 `main.py` 移除 `kf.router` 注册

3. **删除冗余文件**
   - `tools/photo_analyzer.py`、`tools/skill_writer.py`、`tools/social_parser.py`、`tools/version_manager.py`

4. **安全修复**
   - 企微和客服的异常回复不再暴露内部错误信息给用户

## 已知待改进项

| 项目 | 说明 |
|------|------|
| 部署 | 当前依赖 cloudflared 临时隧道，需部署到固定 IP 服务器 |
| Token 缓存 | 内存缓存不支持多 worker，单进程够用 |
| 日志 | 使用 `print` 输出，后续可改 `logging` |
| API 设计 | `/api/chat/{slug}` 的 message 用 query param 传递，应改为 body |
| 会话持久化 | 客服游标 `_kf_cursor` 存内存，重启丢失（已有 drain 兜底） |
