# CLAUDE.md

## 项目概述

wx_chatbot 是一个微信 AI 聊天机器人服务，用户通过 Web 后台上传聊天记录生成 AI 人格，然后通过微信客服或企业微信与 AI 人格对话。

## 技术栈

- **框架**: FastAPI + Jinja2 + Tailwind CSS
- **数据库**: SQLite + SQLAlchemy async (aiosqlite)
- **AI**: OpenAI 兼容接口（当前使用 DeepSeek）
- **部署**: Docker + GitHub Actions + ClawCloud Run (Japan)
- **加密**: 企业微信 AES-256-CBC 消息加解密

## 关键架构决策

- 企业微信回调统一走 `/wx/callback`，客服事件（`kf_msg_or_event`）在 `wechat.py` 中转发给 `services/kf.py` 处理
- 客服消息是拉取模型（sync_msg），不是推送模型。回调只通知"有新消息"，需主动拉取
- 客服会话状态 0/1/2 可直接发消息，状态 3/4 需先转接到状态 0
- AI 配置优先读数据库（AIConfig 表），首次使用需在 `/admin/config` 页面设置
- 人格与客服账号的绑定关系存储在 Persona.meta_json 的 `kf.open_kfid` 字段，启动时通过 `_restore_kf_bindings()` 恢复到内存
- 启动时通过 `_drain_kf_history()` 跳过所有历史客服消息，防止重复处理
- AI 回复经过正则后处理，去除旁白/括号描写内容

## 开发流程

```bash
# 本地开发
pip install -r requirements.txt
uvicorn app.main:app --reload

# 部署：推送代码后 GitHub Actions 自动构建镜像
git push  # → ghcr.io/zovo314/wx_chatbot:latest
# 然后在 ClawCloud Run 点 Update 拉取新镜像
```

## 部署信息

- **服务地址**: https://hydvvzebaapr.ap-northeast-1.clawcloudrun.com
- **回调地址**: https://hydvvzebaapr.ap-northeast-1.clawcloudrun.com/wx/callback
- **出站 IP**: 47.79.37.186（已加入企业微信白名单）
- **镜像**: ghcr.io/zovo314/wx_chatbot:latest

## 文件导航

| 文件 | 职责 |
|------|------|
| `app/main.py` | 入口，启动恢复 KF 绑定和消息游标 |
| `app/routers/wechat.py` | 企业微信回调，处理应用消息和客服事件转发 |
| `app/routers/admin.py` | Web 后台 CRUD、AI 配置、KF 管理 |
| `app/services/kf.py` | 微信客服：拉取消息、发送消息、会话状态管理 |
| `app/services/chat.py` | 对话管理：历史记录、system_prompt 组装、后处理 |
| `app/services/persona_gen.py` | AI 人格生成：memory + persona 并发生成 |
| `app/services/ai_client.py` | OpenAI 兼容客户端封装 |
| `app/services/wx_crypto.py` | 企业微信消息 AES 加解密 |

## 注意事项

- 异常信息不要暴露给终端用户，统一回复"抱歉，处理消息时出错了"
- 微信临时素材 3 天过期，如果后续加表情包功能需注意
- `print` 用于日志输出，后续可改为 `logging`
- 环境变量在 ClawCloud 配置，修改后容器自动重启
