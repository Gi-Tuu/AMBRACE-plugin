# 插件开发文档（公开脱敏版）

> **Public copy — 内部信息已移除，仅供公开仓 docs/**
>
> 生成日期：2026-09-02
>
> 脱敏规则：删除/改写所有内部信息——绝对路径、内部目录名、仓库内部文档引用、个人名/联系方式/服务器地址、
> 真实 .env 值、内部 URL/密钥/端口细节、未公开功能细节（内部代号与排期计划）。保留插件开发契约
> （manifest / 类型 / Hook / SDK / 权限 / 打包）与安全模型。

---

> ## ⚠️ 安全模型（必读）
>
> **插件就是在服务器上运行的任意代码（无沙箱），与后端同权限。** 安装插件等同于授权它在你的服务器上执行代码。
> 请务必阅读并遵守以下准则：
>
> - **只安装可信来源**：仅安装官方或你信任的开发者发布的插件，安装前审阅插件源码与权限声明。
> - **远程市场安装默认关闭**：远程市场安装默认关闭（需管理员显式开启）；本地/内置示例插件不受此开关限制。
> - **安装即授权**：插件声明的 `permissions`（权限类别）在安装/升级前必须经你逐条确认并同意；
>   升级若**新增**权限，需重新确认并同意。
> - **来源与哈希可追溯**：已安装插件记录来源（远程/本地/内置）、来源 url 与 sha256 **实际值**（即使索引未提供），
>   可用于校验包是否被篡改；签名校验接口已预留（当前不强制）。
>
> 权限类别：`write_memory`（读写记忆，可能污染）、`send_message`（主动发消息）、`douyin_publish`（公开发布），
> 以及只读组 `persona:read` / `memory:read` / `life:read` / `relationship:read`。

---

## 目录

1. [快速开始](#一快速开始)
2. [插件结构](#二插件结构)
3. [manifest.json 完整参考](#三manifestjson-完整参考)
4. [插件类型](#四插件类型)
5. [Hook 参考](#五hook-参考)
6. [SDK API 参考](#六sdk-api-参考)
7. [插件桥 API](#七插件桥-api)
8. [权限与安全](#八权限与安全)
9. [打包与安装](#九打包与安装)
10. [调试与排错](#十调试与排错)
11. [MCP 与插件的区别](#十一mcp-与插件的区别)

---

## 一、快速开始

### 零代码插件（5 分钟）

创建一个目录 `my_skill/`，在里面放一个 `manifest.json`：

```json
{
  "name": "my_skill",
  "version": "1.0.0",
  "description": "我的第一个技能",
  "author": "your_name",
  "type": "prompt",
  "hooks": [],
  "permissions": [],
  "config": {
    "prompt": {
      "trigger": ["翻译", "帮我翻译"],
      "systemPrompt": "你是一个专业翻译。用户要求翻译时，先识别语言，再给出准确、流畅的翻译，最后附一条文化注释。",
      "description": "翻译助手"
    }
  }
}
```

打包成 zip（manifest.json 在 zip 根目录），在扩展页上传安装，开启开关。聊天中发"翻译这句话：Hello world"即可触发。

### 代码插件

在上面的目录里加一个 `main.py`：

```python
from app.plugins import sdk

@sdk.hook("context_inject")
async def inject(ctx):
    ctx["context_messages"].append({
        "role": "system",
        "content": "【我的插件】当前时间是 " + _now()
    })

@sdk.hook("after_generate")
async def after(ctx):
    reply = ctx.get("reply_text", "")
    sdk.log("AI 回复了 %d 字", len(reply))

def _now():
    from datetime import datetime
    return datetime.now().strftime("%H:%M")
```

开启插件后，每次 AI 回复都会带上当前时间注入。

---

## 二、插件结构

### 目录布局

```
my_plugin/
├── manifest.json    # 必需：插件元信息与配置
├── main.py          # 可选：Python 代码插件（零代码插件不需要）
├── page.html        # 可选：插件设置页/展示页（hybrid 类型）
├── static/          # 可选：页面资源（css/js/图片）
└── README.md        # 可选：说明文档
```

### 两个加载位置

| 位置 | 说明 |
|------|------|
| 内置示例 | 随项目分发，进开源包 |
| 用户安装 | 用户通过 zip 上传或市场安装，不进版本库 |

### 加载流程

```
扫描目录 → 读取 manifest.json → 校验 → 加载 main.py（如有）
→ 注册 hook/action/router → 同步到插件表 → 等待启用
```

- 插件默认**关闭**，安装后需手动开启
- 启用/禁用/配置修改通过 API 或扩展页操作，无需重启
- 插件异常（加载失败、hook 抛错、超时）**完全隔离**，不影响主链路

---

## 三、manifest.json 完整参考

```json
{
  "name": "my_plugin",
  "version": "1.0.0",
  "description": "插件描述（必填，500 字以内）",
  "author": "作者名",
  "category": "plugin",
  "type": "http",
  "hooks": ["context_inject"],
  "permissions": [],
  "config": {},
  "page": "page.html",
  "icon": "📅",
  "hook_timeout": 10,
  "usage": "使用说明（展示在扩展页）"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 唯一标识，1-64 字符，仅允许 `A-Za-z0-9_-`（防路径穿越） |
| `version` | string | ✅ | 语义化版本号，如 `"1.0.0"` |
| `description` | string | ✅ | 插件描述，≤500 字 |
| `author` | string | ❌ | 作者名，≤100 字 |
| `category` | string | ❌ | `"plugin"`（默认）或 `"mcp"`（仅 UI 分类，不改变行为） |
| `type` | string | ❌ | 插件类型：`http` / `prompt` / `chat` / `workflow` / `hybrid`（默认 `http`） |
| `hooks` | string[] | ❌ | 声明使用的 hook 列表，必须是[合法 hook 名](#五hook-参考) |
| `permissions` | string[] | ❌ | 声明需要的权限：`write_memory` / `send_message` / `douyin_publish` / `persona:read` / `memory:read` / `life:read` / `relationship:read`（安装/升级前需用户逐条同意） |
| `config` | object | ❌ | 默认配置，用户可在扩展页覆盖；不同 type 有不同 schema |
| `page` | string | ❌ | 插件页面入口相对路径（如 `"page.html"`），不能含 `..` 或绝对路径 |
| `icon` | string | ❌ | 图标名或 emoji，≤32 字符 |
| `hook_timeout` | number | ❌ | 单个 hook 超时秒数（1-60），不填用全局默认 10 秒 |
| `usage` | string | ❌ | 使用教程文本，展示在扩展页 |

### 校验规则

- `name` 不合法 → 拒绝加载
- `hooks` 含未知 hook → 拒绝加载
- `permissions` 含未知权限 → 拒绝加载
- `type=prompt` 必须提供 `config.prompt`，且通过 prompt schema 校验
- `type=chat` 必须提供 `config.chat`
- `type=workflow` 必须提供 `config.workflow`
- `page` 扩展名必须在白名单：`.html .htm .css .js .mjs .json .png .jpg .jpeg .gif .webp .svg .woff .woff2 .ttf .ico .txt .md`
- `page` 绝不能是 `.py .pyc .pyd .so .dll .exe`

---

## 四、插件类型

### 4.1 prompt（零代码·触发词注入）

用户消息命中触发词时，自动注入 systemPrompt。适合给 AI 加"技能"。

```json
{
  "type": "prompt",
  "config": {
    "prompt": {
      "trigger": ["写诗", "作诗"],
      "systemPrompt": "你是一位现代诗人……",
      "description": "根据话题即兴写短诗"
    }
  }
}
```

| 字段 | 限制 |
|------|------|
| `trigger` | 非空数组，≤20 个，每个 ≤20 字符（子串匹配，非正则） |
| `systemPrompt` | 非空，≤8000 字符 |
| `description` | ≤200 字符 |

### 4.2 chat（零代码·独立角色）

定义一个可在"AI 好友"中对话的独立角色。

```json
{
  "type": "chat",
  "config": {
    "chat": {
      "name": "英语老师",
      "persona": "你是一位耐心的英语老师，用中英双语交流……",
      "greeting": "Hi! What shall we learn today?",
      "description": "陪练英语口语"
    }
  }
}
```

| 字段 | 限制 |
|------|------|
| `name` | ≤50 字符 |
| `persona` | 非空，≤8000 字符 |
| `greeting` | ≤500 字符 |
| `description` | ≤200 字符 |

### 4.3 workflow（零代码·定时工作流）

用节点+连线定义自动化流程。

```json
{
  "type": "workflow",
  "config": {
    "workflow": {
      "templates": [
        {
          "id": "daily_summary",
          "name": "每日总结",
          "description": "每晚 22 点总结当天",
          "template": {
            "nodes": [
              {"id": "start", "type": "trigger", "config": {"cron": "0 22 * * *"}},
              {"id": "summarize", "type": "llm", "action": "summarize",
               "config": {"prompt": "总结今天的重要事件与心情"}}
            ],
            "edges": [{"from": "start", "to": "summarize"}]
          }
        }
      ]
    }
  }
}
```

| 字段 | 限制 |
|------|------|
| `templates` | 1-10 个，id 唯一 |
| `nodes` | 非空，≤50 个，id 唯一，必须有 type/action |
| `edges` | ≤100 条，from/to 必须引用存在的节点，不允许自环 |

### 4.4 http（代码插件）

传统 Python 代码插件，通过 `main.py` + SDK 装饰器注册 hook/action/router。需要写 Python。

### 4.5 hybrid（混合）

同时包含配置型能力（prompt/chat）和代码能力（main.py），还可以带 `page` 页面。适合复杂插件：配置驱动 + 自定义 API + 设置页。

---

## 五、Hook 参考

Hook 是插件介入 AI 生命周期的入口。用 `@sdk.hook("hook_name")` 注册。

### Hook 列表

| Hook | 触发时机 | ctx 关键字段 | 常见用途 |
|------|----------|-------------|----------|
| `context_inject` | 每次生成前，拼装上下文时 | `user_id`, `character_id`, `session_id`, `user_message`, `context_messages`(list) | 注入 system 提示、天气、外部数据 |
| `before_generate` | LLM 调用前 | 同上 + `context_messages` | 修改/追加上下文 |
| `after_generate` | LLM 返回后 | `reply_text`, `final_state` | 日志、后处理、统计 |
| `memory_search` | 记忆检索时 | `query`, `user_id`, `character_id` | 向召回结果注入额外"记忆"（返回 list） |
| `memory_written` | 新记忆写入后 | `memory` 对象 | 同步到外部、触发联动 |
| `proactive_candidate` | 主动消息候选生成 | `character_id`, `user_id`, `candidates`(list) | 提供主动消息内容候选 |
| `schedule_tick` | 定时调度（每 N 分钟） | `timestamp` | 定时拉取数据、周期性任务 |
| `http_router` | 启动时 | 无（通过 `sdk.router()` 注册路由） | 提供自定义 HTTP API |

### context_inject / before_generate

```python
@sdk.hook("context_inject")
async def inject(ctx):
    # ctx["context_messages"] 是 OpenAI 格式的消息列表，可直接 append
    ctx["context_messages"].append({
        "role": "system",
        "content": "【插件名】注入内容"
    })
```

- 同步或 async 函数均可
- 异常被捕获并打日志，不影响 AI 回复
- 默认 10 秒超时（可在 manifest `hook_timeout` 调整，1-60 秒）

### after_generate

```python
@sdk.hook("after_generate")
async def after(ctx):
    reply = ctx.get("reply_text", "")
    state = ctx.get("final_state", {})
    sdk.log("AI 回复了 %d 字", len(reply))
```

### memory_search

```python
@sdk.hook("memory_search")
def inject_memory(ctx):
    query = ctx.get("query", "")
    if "天气" in query:
        return [{
            "id": -1001,           # 负数虚拟 ID，避免与真实记忆冲突
            "content": "【插件】今天晴天",
            "type": "plugin",
            "importance": 5.0,
        }]
    return None  # 不注入
```

- 返回 list 时，结果合并进记忆召回
- 返回 None 不影响

### proactive_candidate

```python
@sdk.hook("proactive_candidate")
async def candidate(ctx):
    return {
        "content": "该喝水啦！",
        "priority": 5,
        "plugin": "my_plugin",
    }
```

### http_router

```python
from app.plugins import sdk

router = sdk.router()  # prefix=/api/v1/plugins/<name>，自动要求登录态

@router.get("/status")
async def status():
    return {"ok": True, "plugin": "my_plugin"}
```

- 路由在插件加载时自动挂载到 FastAPI
- 所有插件路由**强制要求登录态**（防匿名调用）
- 路由内可使用 `Depends(get_current_user_id)` 获取用户 ID

### schedule_tick

```python
@sdk.hook("schedule_tick")
async def tick(ctx):
    # 周期性执行（间隔由调度器控制）
    await fetch_and_cache_data()
```

---

## 六、SDK API 参考

导入方式：`from app.plugins import sdk`

### sdk.hook(hook_name)

装饰器，注册函数为指定 hook 的处理函数。只能在 `main.py` 被加载时调用。

```python
@sdk.hook("context_inject")
async def my_hook(ctx): ...
```

### sdk.action(action_name)

装饰器，注册插件自定义行为。与 hook 的广播不同，action 由调度器**定向调用**。注册后自动成为 Agent 可调用的工具（工具名 `插件名.action名`）。

```python
@sdk.action("reply_comment")
async def reply(payload):
    comment = payload.get("social_event", {})
    # 处理逻辑
    return True  # True=成功
```

### sdk.log(msg, *args)

写日志到后端日志，自动带插件名前缀。支持 `%s` 格式化。

```python
sdk.log("处理完成")
sdk.log("用户 %d 的数据已更新", user_id)
```

### sdk.get_config() -> dict

读取插件配置。返回 manifest 默认值与用户在扩展页保存的覆盖值的合并结果。

```python
cfg = sdk.get_config()
channel = cfg.get("channel", "default")
```

### sdk.require_permission(perm) -> None

校验插件是否声明了指定权限，未声明则抛 `PermissionError`。通常不需要手动调用，`save_memory`/`send_message` 内部已调用。

```python
sdk.require_permission("write_memory")
```

### await sdk.save_memory(user_id, character_id, memory_type, content, importance=2, **kwargs)

写入 AI 记忆。**需要 manifest 声明 `permissions: ["write_memory"]`**。

```python
await sdk.save_memory(
    user_id=1,
    character_id=1,
    memory_type="insight",
    content="用户喜欢在晚上写代码",
    importance=4,
)
```

- 复用主链路 `save_memory`，走查重/强化/衰减
- 记忆来源标记为插件

### await sdk.send_message(character_id, user_id, content, message_type="plugin") -> bool

代表角色向用户发送主动消息。**需要 manifest 声明 `permissions: ["send_message"]`**。

```python
await sdk.send_message(
    character_id=1,
    user_id=1,
    content="提醒：你设定的休息时间到了",
    message_type="plugin",
)
```

- 复用主链路发送逻辑，自动取最新会话
- 受每小时主动消息限额约束

### sdk.router() -> APIRouter

创建插件专属 FastAPI 路由。prefix 为 `/api/v1/plugins/<name>`，自动要求登录态。

```python
router = sdk.router()

@router.get("/data")
async def get_data(user_id: int = Depends(get_current_user_id)):
    return {"user": user_id, "data": ...}
```

---

## 七、插件桥 API

插件前端页面（`page.html`）可通过统一桥接口调用后端能力，端点：

```
POST /api/v1/plugins/<name>/bridge
```

### 可用 API（白名单）

| API | 说明 | 参数 |
|-----|------|------|
| `ai` | 调用 LLM（走插件专用限额） | `{messages, model?, temperature?}` |
| `getAiList` | 获取 AI 角色列表 | 无 |
| `getAiInfo` | 获取指定角色信息 | `{aiId}` |
| `openChat` | 跳转到指定角色的聊天页 | `{aiId}`（缺省则进入角色选择） |
| `getUserInfo` | 获取当前用户信息 | 无 |
| `store.set` | KV 存储（插件私有） | `{key, value}`，value ≤100KB，key ≤128 字符 |
| `store.get` | 读取 KV | `{key}` |
| `http` | HTTP 代理（有 SSRF 防护） | `{url, method?, headers?, body?}` |
| `toast` | 弹出轻提示 | `{msg}` |
| `copy` | 复制文本到剪贴板 | `{text}` |
| `navigate` | 打开指定链接 | `{url}` |
| `call` | 调用其他桥 API 的统一入口 | `{api, params}` |

> `openChat` / `toast` / `copy` / `navigate` 为**前端能力**，由客户端（WebView）直接执行，不经过本桥端点；其余 API 走 `POST /api/v1/plugins/<name>/bridge`。

### 限流

- `ai` 调用：每用户每插件每分钟 ≤10 次，每天 ≤200 次（可配置）
- `http` 代理：禁止访问内网/本地地址（除非管理员显式放行）；默认只允许 HTTPS

### 前端桥 SDK（页面内）

插件页面运行在扩展页 webview 中，可通过全局对象 **`window.Ambrace`** 调用桥能力（方法均返回 Promise）：

- `Ambrace.call(api, params)`：调用任意桥 API 的统一入口
- `Ambrace.ai(params)` / `Ambrace.getAiList()` / `Ambrace.getAiInfo(aiId)` / `Ambrace.openChat(aiId)` / `Ambrace.getUserInfo()`
- `Ambrace.store.set(key, value)` / `Ambrace.store.get(key)`
- `Ambrace.toast(msg)` / `Ambrace.copy(text)` / `Ambrace.navigate(url)` / `Ambrace.http(url, method?, data?, headers?)`

> `window.AmbraceBridge` 只是底层 `postMessage` 通道，一般无需直接使用，请统一用 `window.Ambrace.*`。

```javascript
// 页面内调用桥
window.Ambrace.call("ai", {
  messages: [{role: "user", content: "你好"}]
}).then(resp => console.log(resp));
```

---

## 八、权限与安全

> ⚠️ **仅安装可信插件**：本插件系统运行在后端**进程内（无沙箱）**，插件拥有与后端同等的进程权限
> （可读写文件、访问网络、调用 AI 能力、读写记忆）。请**只从官方或你信任的开发者来源**安装插件，
> 安装前务必审阅插件源码与权限声明；远程市场的第三方插件与本地安装同样无沙箱。

### 权限模型

| 权限 | 能力 | 风险 |
|------|------|------|
| 无 | hook 注入、读配置、自定义 API | 低 |
| `write_memory` | 写入 AI 记忆 | 中（可污染记忆） |
| `send_message` | 主动给用户发消息 | 中（可骚扰用户） |
| `douyin_publish` | 发布内容 | 高（公开内容发布） |
| `persona:read` / `memory:read` / `life:read` / `relationship:read` | 只读：读取人设/记忆/生活状态/关系网 | 低（只读） |

### 工具权限三档

插件通过 `@sdk.action` 注册的行为自动成为 Agent 工具，受全局权限系统管控：

- **ALLOW**：自动执行
- **ASK**：执行前需用户确认（高风险工具默认）
- **FORBID**：禁止执行

只读低风险工具可在 ToolSpec 标记 `ask_auto_allow=True`，ASK 档下不打扰用户直接放行。

### 安全机制

| 机制 | 说明 |
|------|------|
| 安装限制 | 仅主账号可安装/卸载插件 |
| zip 安全 | 大小上限、文件数上限、解压上限、防路径穿越/符号链接/绝对路径 |
| 路由鉴权 | 所有插件 HTTP 路由强制登录态 |
| SSRF 防护 | 桥 HTTP 代理禁止内网/本地地址 |
| Hook 超时 | 默认 10 秒，超时中断不阻塞主链路 |
| 异常隔离 | 单个插件 hook/action 抛错只打日志，不影响 AI 回复和其他插件 |
| 环境隔离 | Python 插件运行在后端进程内（无沙箱），请只安装可信插件 |
| 页面资源 | 页面文件扩展名白名单，`.py/.pyc/.pyd/.so/.dll/.exe` 绝不提供服务 |

### 给插件开发者的安全建议

1. 不要在插件代码里硬编码 API Key，让用户在 config 里填
2. `http` 桥调用外部 API 时校验 URL，不要把用户输入直接拼进 URL
3. 写记忆前确认内容准确，避免污染 AI 长期记忆
4. 主动消息不要过于频繁，受限额约束但也要考虑用户体验
5. 长耗时操作用 `schedule_tick` 异步做，不要阻塞 `context_inject`

---

## 九、打包与安装

### 打包

将插件目录打包为 zip，**manifest.json 必须在 zip 根目录**（不要多套一层文件夹）：

```bash
cd my_plugin
zip -r ../my_plugin.zip ./*
```

正确结构：
```
my_plugin.zip
├── manifest.json
├── main.py
└── page.html
```

错误结构（会被拒绝）：
```
my_plugin.zip
└── my_plugin/
    └── manifest.json
```

### 安装方式

1. **页面上传**：扩展页 → 安装插件 → 选择 zip
2. **API 上传**：`POST /api/v1/plugins/install`（multipart/form-data，字段 `file`）
3. **远程市场**：`POST /api/v1/marketplace/{name}/install`（从配置的市场 index 安装）
4. **手动放置**：解压到用户安装目录 `<name>/`，重启或调重新扫描 API

> 插件市场默认拉取官方索引（可离线降级）；自建市场用 `PLUGIN_MARKET_URL` 覆盖；
> 远程安装需服务端显式开 `PLUGIN_ALLOW_REMOTE_INSTALL=true` 且只装可信来源。

### 安装后

1. 在扩展页找到插件，开启开关
2. 如有 config，点击配置填入必要参数
3. 部分插件需要额外权限确认
4. 代码插件无需重启服务（安装时自动重新扫描加载）

---

## 十、调试与排错

### 日志

插件日志写入后端日志（带 `[plugin:插件名]` 前缀）：

```
[plugin:weather_brief] 已注入天气: 晴 28°C
[plugin:browser_demo] hook context_inject 超时（已耗时 10.2s，限制 10s）已中断
```

用 `sdk.log()` 输出自己的调试信息。

### 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 安装后列表看不到 | manifest 校验失败 | 检查 name 正则、必填字段、type/config 匹配 |
| 开启后无效果 | hook 未触发或抛异常 | 看日志是否有 warning；确认 hook 名拼写 |
| `sdk.hook 只能在插件 main.py 加载时调用` | hook 装饰器在错误的时机调用 | 确保在 main.py 顶层调用，不要在函数内延迟调用 |
| `未声明权限 write_memory` | manifest 缺 permissions | 在 manifest.json 的 permissions 数组加上 `"write_memory"` |
| 路由 401 | 插件路由要求登录态 | 请求带 Authorization header |
| hook 超时 | 处理时间超过 hook_timeout | 优化逻辑或在 manifest 调大 hook_timeout（≤60） |
| 页面资源 404 | page 路径错误或扩展名不在白名单 | 检查相对路径、扩展名 |
| zip 安装报"路径穿越" | zip 内含 `../` 或绝对路径 | 重新打包，确保只有相对路径 |

### 本地开发技巧

1. 直接在用户安装目录 `<name>/` 开发，改完 main.py 后调重新扫描（或重启服务）
2. 也可以在示例目录下放开发中的插件（会进版本库，适合贡献示例）
3. 用 `sdk.log()` 代替 print（print 输出可能不被日志系统捕获）
4. hook 函数尽量短小，长任务丢 `schedule_tick` 或后台任务

---

## 十一、MCP 与插件的区别

AMBRACE 的"mcp"分类目前只是 UI 标签。**标准 MCP 协议支持正在规划中**。

| 维度 | AMBRACE 插件 | 标准 MCP Server |
|------|-------------|-----------------|
| 语言 | Python | 任意语言 |
| 运行方式 | AMBRACE 进程内 | 独立子进程或远程服务 |
| 接入方式 | 本文档的 SDK/hook | MCP 协议（stdio/SSE） |
| 能力 | hook 注入 + action + 路由 + 页面 | tools/resources/prompts |
| 适合 | 深度集成 AI 生命周期 | 通用工具（文件系统等） |

如果你想做的是"让 AI 调用某个通用工具"，等 MCP 支持后可以直接用标准 MCP Server；如果你想深度介入 AI 的思考/记忆/生活，用 AMBRACE 插件 SDK。
