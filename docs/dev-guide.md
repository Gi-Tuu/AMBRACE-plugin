# 开发者指南（公开脱敏版）

> **Public copy — 内部信息已移除，仅供公开仓 docs/**
>
> 生成日期：2026-09-02
>
> 脱敏规则：删除/改写所有内部信息——绝对路径（盘符/用户目录）、内部目录名、仓库内部文档结构引用、个人名/
> 联系方式/服务器地址、真实 .env 值、内部 URL/密钥/端口细节、未公开功能细节（内部代号与排期计划）。
> 本文只保留通用开发工作流、工程规范与跨模块指引，不披露逐条内部变更历史。

## 项目形态

- 后端：FastAPI 应用，位于 `backend/app/`；依赖与虚拟环境在 `backend/.venv`。
- 前端：Flutter 应用，位于 `flutter_app/`。
- 数据库迁移：Alembic 版本链；启动时幂等兼容层兜底（详见 `docs` 迁移规范）。
- 工程规范与认知链路约定集中在仓库内文档，动手前先读对应文档。

## 环境准备

- 后端：安装依赖（`backend/requirements.txt` + 开发依赖 `backend/requirements-dev.txt`），建议 Python 3.12+。
- 前端：安装 Flutter SDK，依赖由包管理工具解析。
- **配置**：通过根目录 `.env` 提供环境变量（模型 API Key、数据库 URL、端口、功能开关等）；未配置时使用安全默认值。
  敏感配置（如 API Key）不要提交进版本库，用占位符/示例文件说明。

## 常用命令

### 后端

```bash
# 静态检查（ruff，仅启用 F 类：未使用导入/变量、未定义名、f-string 问题）
.venv/Scripts/python.exe -m ruff check backend/app

# 后端测试（放到 backend/ 目录执行）
.venv/Scripts/python.exe -m pytest tests -q

# 一键验证（静态检查 + 编译检查 + 测试 + 前端 analyze + 前端测试 + 可选接口冒烟）
.venv/Scripts/python.exe scripts/verify.py [--smoke]
```

### 前端

```bash
# 静态检查
flutter analyze

# 前端测试
flutter test

# 编译发行 APK（release）
flutter build apk --release
```

## 项目结构（后端分层）

- `backend/app/agent/` 认知循环（感知 → 上下文组装 → 单次 LLM → 反思）
- `backend/app/api/` HTTP 路由（对话 / 角色 / 记忆 / 日记 / 朋友圈 / 宠物 / 状态 / 生活 / 表情 / 市场 / 群聊 / 游戏 / MCP / 账号 / 插件 / 系统等域）
- `backend/app/auth/` 认证（登录鉴权、密码策略）
- `backend/app/db/` SQLite + 向量库；Alembic 迁移版本链 + 启动幂等兼容层
- `backend/app/events/` 进程内事件总线（异步发布/订阅，异常隔离）
- `backend/app/games/` 群聊游戏引擎
- `backend/app/life/` AI 自主生活状态机与决策循环
- `backend/app/mcp/` MCP 协议层（连接管理 / 多用户隔离 / 工具适配）
- `backend/app/memory/` 记忆域（统一写入 / 衰减 / 去重 / 抽取 / 嵌入 / BM25 / 混合检索）
- `backend/app/models/` ORM 模型；`config/` 子包存各配置模型
- `backend/app/plugins/` 插件框架（manifest / 注册表 / SDK / 配置扩展点 / zip 安全）
- `backend/app/scheduler/` 主动交流仲裁与各类生成器
- `backend/app/services/` 业务层（对话 / 权限 / 配置解析 / 推送 / 语音 / 上传 / 天气 / 表情市场 / 插件桥等）
- `backend/app/tools/` 内置工具（搜索 / 备忘 / 日历 / 图像）
- `backend/app/utils/` 时间工具（UTC naive 口径）等
- `backend/app/voice/` 语音实时交互
- `backend/app/weave/` 织库·全景记忆

## 工程约定

- **单一事实源**：人设 / 记忆 / 状态 / 关系 / 生活 / 日程 / 世界状态 / Agent Runtime 各领域有唯一权威实现。
- **时间**：数据库统一存 UTC（naive），展示时换算本地时区；比较需补时区信息。
- **记忆写入**：统一走记忆服务（双写结构化 + 向量）。
- **LLM 调用**：统一走客户端（用量日志、思考开关、多级配置回退）。
- **工具执行**：统一走执行器（权限三档 + 生命周期钩子，勿绕过直调插件 hook）。
- **新增 HTTP 路由**：必须在应用入口显式导入并挂载。
- **事件总线**：用于模块间解耦，不直接改其他模块内部状态。
- **开关集中**：功能开关集中登记、可回退；角色级开关集中在联动开关。
- **文档纪律**：功能/修复交付需同步登记（对外更新公告 + 开发者变更记录 + 规划台账），同一日同类内容合并为一条。

## 插件开发

插件是扩展 AI 能力的主要途径（契约见 `plugin-development.md` / `extension-contract.md`）：

- **零代码插件**：`manifest.json` + 类型 `prompt` / `chat` / `workflow`。
- **代码插件**：`main.py` + SDK 装饰器注册 `hook` / `action` / `router`。
- **权限模型**：插件声明 `permissions`，安装/升级前需用户逐条同意；高风险能力（写记忆 / 主动发消息 / 公开发布）需显式授权。
- **安全**：插件与后端同进程（无沙箱），仅安装可信来源；`http` 桥有 SSRF 防护；页面资源扩展名白名单。
- **打包**：`manifest.json` 在 zip 根目录；安装支持页面上传 / API / 远程市场 / 手动放置。

## MCP 接入

MCP（模型上下文协议）用于把外部通用工具接入 Agent：

- 支持 `stdio` / `SSE` / `streamable-http` 连接。
- 多用户隔离：按用户隔离工作目录与归属，工具作用域独立。
- SSRF 防护：禁用内网 + DNS 绑定防护。
- 工具声明注入上下文；资源/提示词只读展示；调用日志；权限三档。

## 部署

概括见 `docker-deploy.md`：

- 支持 Docker（多架构镜像）与脚本式部署（Windows / Linux-macOS）。
- 数据目录与模型目录挂载持久化；`.env` 只读挂载；端口 / CORS 可通过环境变量配置。
- 数据库升级走 Alembic：升级前先备份。

## 验证与回归

- 后端：ruff 0；全量 pytest 基线不退；改动涉及的新增用例必须覆盖对应逻辑。
- 前端：flutter analyze 0；flutter test 全绿。
- 涉及多语种 UI 文案改动时，新增文案成对补齐（zh/en），占位符一致，并跑 `flutter analyze` 验证。

> 本文不披露逐条内部变更记录、内部代号、具体实现路径与真实配置值；如需完整实现细节请以源码为准。
