# 扩展类型 / 权限 / Hook 契约（公开脱敏版）

> **Public copy — 内部信息已移除，仅供公开仓 docs/**
>
> 生成日期：2026-09-02
>
> 脱敏规则：删除/改写所有内部信息——绝对路径、内部目录名、仓库内部文档引用、个人名/联系方式/服务器地址、
> 真实 .env 值、内部 URL/密钥/端口细节、未公开功能细节（内部代号与排期计划）。保留扩展体系公共 API 契约
> （类型 / Hook / 权限 / SDK / 版本化与弃用承诺）。

> 本文是 AMBRACE 扩展体系的**公共 API 契约**：一经发布即视为对第三方插件的承诺。
> 变更须遵守语义化版本 + 弃用周期（见 §5）。

## 1. 扩展类型（manifest.type / category）

| 类型 | 代码 | 交互面 | 必需权限 | 状态 |
|---|---|---|---|---|
| `prompt` / `chat` / `workflow` | 否（纯声明） | 注入 / 迷你人格 / 流程模板 | 无 | 已有 |
| `http` / `hybrid`（page） | 是（同进程） | hooks + actions + 自带 router + 静态页 | 按声明 | 已有 |
| MCP（category=`mcp`） | 外部进程 | Agent 工具（stdio/SSE/HTTP） | 工具作用域 | 已有 |
| `game_pack` / `provider` / `channel` / `content_pack` / `device_driver` / `proactive_strategy` | 见扩展化方案 | register_* 注册口 | 见 §3 | game_pack / provider / content_pack 已落地；channel / device_driver / proactive_strategy 规划中（随扩展化批次落地） |

## 2. Hook 契约

### 2.1 白名单

**collect 型**（插件可贡献返回值，参与主链路结果；有返回条数/体积约束）：
- `memory_search` — 追加/调整召回记忆（主结果让位给插件追加项）
- `proactive_candidate` — 提供主动发言候选（日限额由插件自守，统一频控）

**notify 型**（只观察，返回值忽略；不得改写流程数据）：
- `context_inject` — 往系统上下文追加内容（注入型，唯一例外：可追加文本）
- `before_generate` / `after_generate` — 生成前追加/改写、生成后处理回复（改写型）
- `memory_written` — 记忆落库后通知
- `schedule_tick` — 每 30s 调度 tick 通知（插件自行节流）
- `http_router` — 挂载插件自有 API（非消息钩子，路由注册型）
- `tool_call_requested` — 工具调用请求时
- `tool_permission_checked` — 工具权限判定后
- `tool_execution_started` — 工具开始执行
- `tool_result` — 工具产出结果
- `tool_finished` — 工具执行收尾（含幂等重试后）
- `tool_error` — 工具执行异常

> tool_* 六钩子语义均为 notify。

### 2.2 运行时保证（内核承诺，已实现）

- **异常隔离**：单个插件 hook 抛错不影响其他插件与主链路；
- **超时门禁**：默认超时 10 秒，manifest 可声明覆盖，收敛区间 1–60 秒；
- **零 DB 分发**：启用集合进程内缓存，hook 分发不查库；
- **fail-open**：一切 hook 异常静默降级，绝不阻塞主回复/调度。

### 2.3 预留 hook 名（本次只定名不实现，实现前不进白名单）

`message_inbound` / `message_outbound`（渠道与过滤）、`provider_select`（模型选择）、`game_lifecycle`
（开局/回合/结算）、`proactive_filter`（主动消息最终过滤）、`app_startup` / `app_shutdown`（生命周期，随需要）。

## 3. 权限模型

在原 3 个写权限（`write_memory` / `send_message` / `douyin_publish`）基础上新增只读组
`persona:read` / `memory:read` / `life:read` / `relationship:read`（SDK 只读端口专用）。

目标三类枚举（此处仅预告，落地以对应批次为准）：
- **读**：`memory:read` `persona:read` `life:read` `relationship:read`
- **写**：现有 3 个 + 领域窄口
- **外部动作**：`channel:read` `channel:publish` `device:*` `net:outbound` `fs:limited`

安装时展示授权页（要什么/为什么），用户授予后启用；`sdk.require_permission` 点位已有。

## 4. SDK 面

现共 15 个（`plugins/sdk.py`）：
`hook / action / log / get_config / require_permission / save_memory / send_message / router / register_game / register_provider / register_channel` +
只读端口 `get_persona / search_memory / get_relationship / get_life_state / emit`。

Provider 注册口：统一注册 `register_provider(kind, name, factory, meta, source)`，kind ∈ `llm / tts / asr / vision / image / push`；
内置实现走同一注册口。`factory(config)` 每次请求调用，**密钥只经运行时配置下发，禁止打进扩展包**；
选中规则：配置 provider 字段与注册名精确匹配，未匹配时内置兜底；插件停用后不可选；运行时回退开关控制。
可选列表 `list_providers(kind)` 供配置页消费。

渠道端口：定义 **ChannelPort 契约**（`publish / pull_comments / reply_comment / upload_media / binding_status`，
payload 为渠道自解释 dict）+ `register_channel(name, port, meta, source)`（同源重载=替换）；
meta 契约：`label / plugin / permissions（<渠道名>_ 前缀）/ scope / scope_label / scope_desc / risk_level / binding`——
渠道只上报能力与绑定请求，**「每独立主账号全局唯一绑定」裁决在内核**；manifest 声明 `"channel": "<渠道名>"` 的插件
在启动建表前被预加载（渠道自有 ORM 模型在加载期注册进元数据）；内核不持有任何具体渠道名。

只读端口语义：均需对应只读权限；返回脱敏快照（正文截断、不暴露 ORM 对象）；`search_memory` 走内核多路召回
（limit 受限）；`emit` 事件类型必须以插件名为前缀（防伪造内核域事件）。

约束：写操作只走 `save_memory / send_message / register_game / register_provider / register_channel`
（及未来 `register_*`）窄口；禁止 import 内核内部模块（重构即碎）。

插件静态页面：扩展名白名单托管、单文件大小上限。

## 5. 版本化与弃用承诺

- 合法 Hook 名 / 合法权限 / SDK 函数签名 / 注册口一经发布即**公共 API**；
- 变更遵循语义化版本：破坏性变更须提前 **1 个小版本**在白名单/文档中标注弃用，保留兼容期；
- manifest 应声明兼容的核心版本范围（市场审核项，随市场机制落地强制）。

## 6. 信任分级（沿用既定结论）

L0 声明型/内容包（零代码，默认可信）→ L1 代码型（同进程全信任，安装显式授权 + 来源标注）→ L2 MCP（进程隔离）。
子进程沙箱长期不做（见扩展化方案）。
