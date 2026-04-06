# AI人格复刻 — 从 0 开始的完整使用教程

本教程面向零基础用户。跟着做，你会得到：
- 一个挂在云端、永不断线的 AI 人格聊天机器人
- 一个可以通过微信 / 企业微信直接对话的 AI 角色（朋友、家人、前任、偶像、虚构角色都行）

**全程 0 代码操作，不用自己买服务器，不用买域名。总耗时约 60 分钟。**

---

## 你会需要什么

| 类别 | 项目 | 是否收费 |
|---|---|---|
| 账号 | 企业微信（个人也能注册） | 免费 |
| 账号 | GitHub（注册 >180 天可白嫖 ClawCloud） | 免费 |
| 账号 | ClawCloud Run（日本区） | 免费额度够用 |
| 账号 | DeepSeek / 其他 AI 服务 | DeepSeek 约 ¥0.001/千token，聊一个月几毛钱 |
| 设备 | 一台能上网的电脑 | — |

---

# 第 1 部分：账号准备（约 15 分钟）

## 1.1 注册企业微信

1. 打开 https://work.weixin.qq.com/
2. 点**立即注册**
3. 选**自由企业注册**（个人也能填，企业名随便写，比如"张三工作室"）
4. 用手机扫码验证 → 填写基本信息 → 创建完成
5. 下载「企业微信」App 登录进去

✅ **产物**：一个属于你自己的企业微信

> 💡 **注意**：不需要企业认证，不需要营业执照。未认证企业接待客户数上限是 100 人，自用完全够。

## 1.2 注册 DeepSeek（推荐，因为便宜）

1. 打开 https://platform.deepseek.com/
2. 用手机号注册
3. 左侧菜单 → **API Keys** → **创建 API Key**
4. 复制保存这个 Key（格式：`sk-xxxxxxxx...`），**只会显示一次**
5. 左侧 → **充值**，充 ¥10 够用很久

✅ **产物**：一个 DeepSeek API Key

> 💡 用其他 AI 服务也可以，只要是 OpenAI 兼容协议即可（Kimi、通义千问、硅基流动、本地 Ollama 等）。

## 1.3 注册 GitHub

1. 打开 https://github.com/signup
2. 注册完成

> ⚠️ 如果账号注册**未满 180 天**，ClawCloud 不会白送 $5/月 额度。这种情况你可以：
> - 等 180 天
> - 或用自己已有的老账号
> - 或考虑其他托管平台（略）

## 1.4 注册 ClawCloud Run

1. 打开 https://run.claw.cloud/
2. **用 GitHub 账号登录**
3. 登录后能看到控制台，选**日本区**（ap-northeast-1）

✅ **产物**：一个 ClawCloud 账号 + 日本区项目

---

# 第 2 部分：部署服务到云端（约 15 分钟）

## 2.1 Fork 本项目到你的 GitHub

1. 打开本项目仓库（`https://github.com/Zovo314/wx_chatbot`）
2. 右上角点 **Fork**，复制到自己的 GitHub 账号下
3. Fork 完成后进入自己的仓库页面（`https://github.com/你的用户名/wx_chatbot`）

## 2.2 让 GitHub Actions 构建你的镜像

1. 进入你 Fork 的仓库 → 顶部 **Settings** → 左侧 **Actions** → **General**
2. 确保 **Allow all actions** 是开启状态
3. 回到 **Code** 页，随便改一下 README 提交一次（或者点 Actions 标签页手动触发）
4. 等 **Actions** 标签页里的任务变成 ✅（约 2 分钟）

✅ **产物**：一个镜像 `ghcr.io/你的用户名/wx_chatbot:latest`

> ⚠️ 如果构建失败说权限问题：Settings → Actions → General → Workflow permissions → 选 **Read and write permissions** → Save → 重新触发。

## 2.3 在 ClawCloud 创建应用

1. ClawCloud 控制台 → **App Launchpad** → **Create App**
2. 填写：

| 字段 | 填什么 |
|---|---|
| Application Name | `wx-chatbot`（注意：**不能有下划线**） |
| Image | `ghcr.io/你的用户名/wx_chatbot:latest` |
| Usage / CPU | 默认即可（0.2 Core） |
| Usage / Memory | 默认即可（256 MB） |
| Network / Container Port | `8000` |
| Network / Public Access | **勾选** Enable |
| Network / Protocol | HTTPS |

3. **Advanced Configuration → Local Storage**：
   - Path: `/app/data`
   - Size: `1 GB`
   - 这是用来存数据库的，必须配，否则重启数据丢失

4. **Environment Variables**：**先留空，后面再填**
5. 点 **Deploy**

## 2.4 等服务启动 + 拿 URL 和出站 IP

1. 等 Pod 状态变成 **Running**（约 2 分钟）
2. 点开应用详情 → **Network** 区域，复制 **Public Address**
   - 形如：`https://xxxxxxxxxx.ap-northeast-1.clawcloudrun.com`
   - 这就是你的**服务 URL**，记下来

3. 拿出站 IP：
   - 点 **Terminal**（终端图标）进入容器
   - 执行：`python -c "import urllib.request; print(urllib.request.urlopen('https://ifconfig.me').read().decode())"`
   - 记下输出的 IP（日本区通常是 `47.79.37.186`，固定不变）

✅ **产物**：服务 URL + 固定出站 IP

> 💡 **此时服务没配置环境变量会启动失败**，这正常，下一步就去填。

---

# 第 3 部分：企业微信后台配置（约 15 分钟）

## 3.1 创建自建应用

1. 登录 https://work.weixin.qq.com/ 企业微信后台
2. 左侧 → **应用管理** → **自建** → **创建应用**
3. 填写：
   - 应用 Logo：随便传
   - 应用名称：比如 "AI人格"
   - 可见范围：选自己
4. 创建完成后进入应用详情页，**记下这三个值**：
   - **AgentId**（一串数字）
   - **CorpID**（在"我的企业 → 企业信息 → 企业ID"）
   - **Secret**（应用详情页点"查看"，会发到企业微信 App 里）

## 3.2 回填 ClawCloud 环境变量

1. 回到 ClawCloud → wx-chatbot → **Update**
2. **Environment Variables** 区域填入（每行一个，**不要有多余空格**）：

```
WX_CORPID=你的企业ID
WX_CORPSECRET=应用的Secret
WX_AGENTID=应用的AgentId
WX_TOKEN=随便起一个字符串（如 myToken123）
WX_ENCODING_AES_KEY=随机43位字符（数字+大小写字母）

AI_PROVIDER=deepseek
AI_API_KEY=你的DeepSeek API Key
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
AI_MAX_HISTORY=20
```

- `WX_TOKEN`：自己起一个 3-32 位的随机字符串，记下来
- `WX_ENCODING_AES_KEY`：**必须正好 43 位**（大小写字母+数字），可以用这个网页生成：https://www.sexauth.com/tools/randomstring（或自己随机敲）

3. 点 **Update** → 容器自动重启

## 3.3 配置接收消息 API

1. 企业微信后台 → 你的应用详情页 → **接收消息** → **设置API接收**
2. 填写：

| 字段 | 填什么 |
|---|---|
| URL | `你的服务URL/wx/callback` （如 `https://xxx.clawcloudrun.com/wx/callback`） |
| Token | 和 `WX_TOKEN` 一模一样 |
| EncodingAESKey | 和 `WX_ENCODING_AES_KEY` 一模一样 |

3. 点**保存**
   - 如果显示**验证成功** ✅ → 进行下一步
   - 如果显示**回调失败** ❌ → 跳到[第 6 部分：常见问题](#第-6-部分常见问题) 自查

## 3.4 加可信 IP 白名单

应用详情页 → **开发者接口** → **企业可信IP** → 点编辑 → 添加第 2.4 步记下的出站 IP（如 `47.79.37.186`） → 保存

> ⚠️ 不加这个，后续发消息会报 60020 错误。

✅ **此时应用消息通道已经贯通**。你可以在企业微信 App 里打开"AI人格"应用，发一条消息测试。

---

# 第 4 部分：Web 后台初始化 + 创建人格（约 10 分钟）

## 4.1 访问管理后台

浏览器打开：`你的服务URL/admin/`

应该能看到"AI人格复刻"的人格列表（初始为空）。

> ⚠️ 本项目后台**没有登录验证**，建议不要分享 URL 给别人。真的担心可以在 ClawCloud 里给容器加 Basic Auth 反向代理。

## 4.2 配置 AI 参数

顶栏 → **AI 配置**

| 字段 | 填什么 |
|---|---|
| Provider | `deepseek` |
| Model | `deepseek-chat` |
| API Key | 你的 DeepSeek API Key |
| Base URL | `https://api.deepseek.com/v1` |
| Max History | `20` |

保存。

> 💡 这里会覆盖环境变量。之后想换模型只改这里即可。

## 4.3 创建第一个人格

顶栏 → **创建**

| 字段 | 说明 | 示例 |
|---|---|---|
| Slug | 英文/拼音代号，唯一 | `xiaoming` |
| 花名 | 显示名 | 小明 |
| 基本信息 | 一句话关系 | 大学室友 认识八年 上海 产品经理 |
| 性格画像 | 标签+性格 | ENFP 双子座 话痨 嘴硬心软 |
| 上传聊天记录 | 可选 | 微信/QQ 导出的聊天文件 |
| 口述文本 | 可选 | 你想补充的故事、典型对话、难忘瞬间 |

> 💡 **聊天记录如何导出？** 见下文[附录 A](#附录-a聊天记录导出工具)。没有聊天记录也没关系，光靠文字描述也能生成。

点**生成人格** → 等 20-30 秒 → 自动跳转到详情页，你能看到 AI 生成的：
- **人物记忆**（Relationship Memory）
- **人物性格**（5 层 Persona 结构）
- **最终 System Prompt**（对话时真正发给 AI 的）

可以在详情页直接编辑这些文本进一步微调。

## 4.4 测试对话

两种方式：

**方式 A：在后台直接测**（最快）
- 详情页有**测试对话**框，发消息就能看 AI 回复

**方式 B：在企业微信 App 里测**
- 打开企业微信 → 工作台 → 你的应用 → 发消息

---

# 第 5 部分（可选）：接入微信客服

如果你想让**普通微信用户**也能和你的 AI 聊天（不限于企业微信内部），要接入微信客服。

## 5.1 开通微信客服

企业微信后台 → **应用管理** → **微信客服** → 按提示开通（免费）

## 5.2 授权应用调用客服 API

微信客服页面 → **可调用接口的应用** → **修改** → 勾选你之前建的自建应用（"AI人格"） → 保存

## 5.3 在 ClawCloud 加 KF Secret

环境变量加一行：
```
WX_KF_SECRET=你的自建应用的Secret（和 WX_CORPSECRET 一模一样）
```

保存 → 重启。

> 💡 新版企业微信 API 客服没有独立 Secret 了，直接用授权应用的 Secret。

## 5.4 创建客服账号

微信客服页面底部 → **创建账号** → 填名字、上传头像 → 保存

系统会生成一个**客服二维码**，用户扫这个码就能进入聊天。

## 5.5 在后台绑定客服 → 人格

回到 `你的服务URL/admin/kf`：

1. 页面顶部会显示已有的客服账号列表
2. 每个客服旁边下拉选人格 → 点**绑定**
3. 刷新页面看到绑定状态变绿 ✅

## 5.6 让用户来聊

- 把客服二维码发给朋友，或嵌入你的网站
- 用户扫码 → 在微信内聊天 → AI 用绑定的人格自动回复

---

# 第 6 部分：常见问题

## Q1：回调验证失败

**可能原因**（按概率排序）：
1. `WX_TOKEN` / `WX_ENCODING_AES_KEY` 在 ClawCloud 里填的值**和企业微信后台填的不一致**（多一个空格都不行）
2. `WX_CORPID` 是旧企业的或填错了
3. ClawCloud 保存环境变量后容器**还没重启完**，稍等 1 分钟再试
4. URL 末尾多了 `/`

**排查方法**：ClawCloud → Logs → 看启动时有没有异常，看收到回调时具体报什么错。

## Q2：启动失败，日志显示 `获取客服token失败: {errcode: 40001}`

**原因**：`WX_KF_SECRET` 错了，或企业还没开通微信客服。

**修复**：不想用客服就留空，代码已经做了容错，主服务不会受影响。

## Q3：能收到消息但 AI 不回复 / 回复"抱歉，处理消息时出错了"

**可能原因**：
1. AI API Key 错了或余额不足 → 查 DeepSeek 后台
2. `/admin/config` 没配置 AI → 去配一下
3. 网络问题，容器访问不到 DeepSeek → 查 Logs

## Q4：消息发不出去 `errcode: 60020`

**原因**：出站 IP 没加到企业可信 IP 白名单。

**修复**：应用详情 → 开发者接口 → 企业可信 IP → 添加 `47.79.37.186`（或你实际的出站 IP）。

## Q5：客服页面看不到客服账号

**排查**：
1. `WX_KF_SECRET` 填对了吗？
2. 企业微信后台"可调用接口的应用"里勾选了你的应用吗？
3. 有没有实际创建客服账号？

## Q6：企业微信"可信域名"怎么填？

**不用填**，留空。那是给网页 OAuth2 授权用的，本项目用不到。`clawcloudrun.com` 也无法备案到你的企业主体，强行填也填不进去。

## Q7：怎么改代码后让云端生效？

1. 在 GitHub 上改代码并提交
2. GitHub Actions 自动构建新镜像（2 分钟）
3. ClawCloud → wx-chatbot → **Update** → 拉新镜像 → 容器自动重启

## Q8：我想用别的 AI 不用 DeepSeek？

只要是 OpenAI 兼容协议都行。`/admin/config` 里改：
- Base URL
- API Key
- Model

保存后立即生效，不用重启容器。

## Q9：数据存在哪里？会丢吗？

- SQLite 文件在容器的 `/app/data/ex.db`
- ClawCloud 的 Local Storage 是**持久卷**，容器重启/更新镜像都不会丢
- 删除整个 App 会丢，所以建议定期在后台 Download 备份（详情页有导出按钮）

## Q10：费用大概多少？

| 项目 | 月成本 |
|---|---|
| ClawCloud | GitHub >180 天白嫖 $5 额度，实际约 $1-2 |
| DeepSeek | 正常聊天约 ¥1-5 |
| 合计 | **约 ¥10-20/月** |

---

# 附录 A：聊天记录导出工具

要让 AI 更像目标人物，**真实聊天记录是最好的原料**。下面是常见导出方式：

## 微信聊天记录（Mac）

- [WechatExporter](https://github.com/BlueMatthew/WechatExporter)：导出 `.txt` 或 `.html`
- [pywxdump](https://github.com/xaoyaoo/PyWxDump)：导出 `.json`

## 微信聊天记录（Windows）

- [留痕](https://github.com/LC044/WeChatMsg)：最推荐，界面化，导出 `.txt / .html / .csv`
- [WechatMsg](https://github.com/LC044/WeChatMsg)

## QQ 聊天记录

- QQ 自带"消息管理器 → 导出消息记录"，选 `.mht` 或 `.txt` 格式

## 导出后上传

在本项目"创建人格"页面直接**上传文件**即可，项目会自动调用 `tools/wechat_parser.py` / `tools/qq_parser.py` 解析成结构化文本喂给 AI。

---

# 附录 B：环境变量速查表

| 变量 | 必填 | 说明 |
|---|---|---|
| `WX_CORPID` | ✅ | 企业微信企业ID |
| `WX_CORPSECRET` | ✅ | 自建应用的 Secret |
| `WX_TOKEN` | ✅ | 自定义，用于回调验签 |
| `WX_ENCODING_AES_KEY` | ✅ | 43 位，用于回调加解密 |
| `WX_AGENTID` | ✅ | 自建应用的 AgentId |
| `WX_KF_SECRET` | ❌ | 需要客服功能时填，值 = `WX_CORPSECRET` |
| `AI_PROVIDER` | ❌ | 默认 `openai` |
| `AI_API_KEY` | ✅ | AI 服务 API Key |
| `AI_BASE_URL` | ❌ | 默认 OpenAI 官方地址 |
| `AI_MODEL` | ❌ | 默认 `gpt-4o` |
| `AI_MAX_HISTORY` | ❌ | 默认 20 条对话历史 |

---

# 附录 C：完整流程速查图

```
企业微信账号 ──┐
GitHub 账号 ───┼─▶ ClawCloud 部署 ──▶ 服务 URL + 出站 IP
DeepSeek Key ──┘           │
                           ▼
                   填环境变量 + 重启
                           │
                           ▼
               企业微信后台配置回调 ──▶ 保存成功 ✅
                           │
                           ▼
                 可信 IP 加白名单
                           │
                           ▼
             访问 /admin/ → 配 AI → 创建人格
                           │
                           ▼
            企业微信 App 发消息 → AI 回复 ✅
                           │
                    （可选接客服）
                           ▼
           创建客服账号 → 绑定人格 → 分享二维码
                           │
                           ▼
              用户扫码在微信里和 AI 聊天 ✅
```

---

**祝你成功复刻心中的那个 ta！** 🎉

遇到问题欢迎在 GitHub 仓库提 Issue。
