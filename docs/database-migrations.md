# 数据库迁移（Alembic）开发规范（公开脱敏版）

> **Public copy — 内部信息已移除，仅供公开仓 docs/**
>
> 生成日期：2026-09-02
>
> 脱敏规则：删除/改写所有内部信息——绝对路径、内部目录名、仓库内部文档引用、个人名/联系方式/服务器地址、
> 真实 .env 值、内部 URL/密钥/端口细节、未公开功能细节（内部代号与排期计划）。保留迁移纪律原则与通用流程。

## 一、背景与目标

此前数据库初始化逻辑里堆了**大量**建表 / 改列 / 建索引迁移语句（全部用幂等判定补齐列与索引）。这套做法在
「首次部署 / 补丁式升级」时可用，但存在硬伤：

- **跨版本升级不可追溯**：无法回答「当前库到底改了哪些 schema」；
- **模型与库漂移**：某些列/索引只在初始化语句里，不在 ORM 模型里，二者可能不一致；
- **自动生成缺失**：改了模型后无法自动生成对应的迁移脚本。

目标（渐进式，避免把大量历史手工迁移重写为版本链的高风险）：

1. **不破坏存量**：幂等初始化路径继续生效，现有部署无缝升级；
2. **新部署走版本链**：`alembic upgrade head` 在空库上按版本链建表；
3. **未来 schema 变更**：改模型 → `alembic revision --autogenerate` 自动生成迁移脚本入链；
4. **SQLite + 异步引擎兼容**：Alembic 用同步引擎，SQLite 的部分 ALTER 走 `batch_alter_table`。

## 二、架构：幂等兼容层 + Alembic 版本链

采用「**幂等兼容层仍负责 schema 落库，Alembic 负责版本记账**」的双轨设计：

| 角色 | 职责 | 现状 |
|---|---|---|
| 幂等初始化（`init_db`） | 幂等兼容层：建全表 + 存量幂等补丁（补列/补索引/数据回填） | 保持不变，首批部署与存量升级仍靠它保证 schema 到当前模型状态 |
| `alembic`（版本链） | 版本记账 + 未来 schema 变更通道：`upgrade head` / `stamp head` / `revision --autogenerate` | 新增，`head` = 基线迁移 |

**为什么兼容层不改**：兼容层已被存量部署与大量测试依赖。若把所有历史迁移重写为 Alembic 版本链，风险极高，
且与「首次建库仍要幂等补丁」的既有行为冲突。渐进式方案把「schema 落库」与「版本记账」解耦，二者各司其职。

## 三、目录结构（新增）

```
backend/
├── alembic.ini                      # Alembic 配置（纯 ASCII，按 locale 读取，勿写中文）
├── alembic/
│   ├── env.py                       # 迁移环境：同步引擎 + target_metadata=models Base
│   ├── script.py.mako               # 新修订模板
│   └── versions/
│       └── <rev>_initial_baseline.py   # 基线迁移（当前 schema 快照 = 兼容层落库结果）
└── app/db/migrate.py                # 启动对齐助手
```

依赖清单已加入 `alembic>=1.13`。

## 四、常用命令（在 `backend/` 目录执行）

```bash
# 查看版本链 / 当前版本 / 链头
alembic history
alembic current
alembic heads

# 新库：按版本链建表到 head
alembic upgrade head

# 存量库：把当前库标记为已迁移（不执行迁移脚本，只写 alembic_version）
alembic stamp head

# 未来 schema 变更：对比模型自动生成修订
alembic revision --autogenerate -m "add xxx column to yyy"

# 指定 DB 目标（默认数据库 URL；设 DATABASE_URL 环境变量即可，例如：
#   DATABASE_URL="sqlite+aiosqlite:///<tmp>/test.db" alembic upgrade head）
```

> 约定：`alembic` 的 SQLAlchemy URL 不写在 `alembic.ini`，由 `env.py` 从应用配置动态生成（去掉异步驱动
> 后缀得同步 URL）。故可用 `DATABASE_URL` 环境变量指到任意库（含测试临时库）。

## 五、新开发流程（未来 schema 变更）

1. **改模型**：在 ORM 模型里改/加表、列、索引（模型是 schema 的单一事实源）。
2. **生成修订**：`alembic revision --autogenerate -m "描述"` —— 自动对比「当前库」与「模型」，生成迁移脚本。
3. **检查迁移脚本**：打开生成的修订文件确认 DDL 正确。SQLite 下删除列/改列/改约束会以
   `with op.batch_alter_table(...)` 呈现（表重建），需人工核对。
4. **升级验证**：`alembic upgrade head`（本地跑一次确认无冲突）。
5. **兼容层不再新增手工 ALTER**：自本方案起，新增 schema 变更一律走 Alembic 修订；幂等兼容层保持既有
   补丁不再追加（避免「模型—库—版本链」三方漂移）。

## 六、启动对齐逻辑

应用启动在幂等初始化（`init_db`）之后调用启动对齐助手（同步引擎，跑在线程池不阻塞事件循环），按库状态对齐
`alembic_version` 到 `head`：

| 当前库状态 | 动作 | 返回值 |
|---|---|---|
| 已在 `head` | 无操作 | `already_at_head` |
| 无 `alembic_version`（全新库或从未版本化） | `alembic stamp head` | `stamped:<head>` |
| 版本号在本链之外的存量库（历史遗留/被移除的试验版本） | `alembic stamp head --purge`（清旧历史再标） | `re-stamped:<old>-><head>` |
| 已知旧版本且落后于 `head` | `alembic upgrade head` | `upgraded:<old>-><head>` |

**关键点**：幂等初始化已把任意库的 schema 对齐到当前模型状态，因此「存量/新装」都可在初始化之后安全地
`stamp head`；仅当存在未应用的已知历史版本（未来加列等）才真正 `upgrade`。启动调用做了防御性异常处理
（失败仅告警，不阻断启动），保证幂等路径始终可用。

## 七、SQLite + 异步引擎兼容要点

- **env.py 用同步引擎**：应用是异步驱动（`sqlite+aiosqlite`），Alembic 迁移/自动生成需同步驱动（`sqlite3`）。
  `env.py` 的同步 URL 转换把异步前缀去掉（未来切 PostgreSQL 同理）。
- **`render_as_batch=True`（仅 SQLite）**：SQLite 不支持直接删除/修改列与约束、部分 ALTER 受限，Alembic 会
  自动用「新表复制 → 改名」的重写策略（`op.batch_alter_table`）降级。非 SQLite 不开启。
- **`compare_type=True`**：自动生成时对比列类型，能捕捉类型漂移。

## 八、基线迁移

基线迁移由 `alembic revision --autogenerate` 在**空库**上对比模型生成，等价于「兼容层落库结果」的 schema 快照
（全部表、全部列与索引，含原兼容层手工建的高频索引——这些索引已回填进对应 ORM 模型 `__table_args__`，
使模型成为 schema 的单一事实源）。

**验证结论**：空库 `alembic upgrade head` 建表结果与兼容层落库结果一致；在已 upgrade 到 head 的库上
`alembic revision --autogenerate` 生成空修订（基线对齐，无多余差异）；存量库副本 `alembic stamp head`
（及启动对齐助手）= head 成功，schema 无损。

## 九、回滚与取消

- 单个修订的 `downgrade()`：
  - 基线迁移 `downgrade` 会按逆序 drop 所有表（慎用于生产，仅演示）；
  - 后续修订按需写 `downgrade()`（SQLite 下删列/表仍受 `batch_alter_table` 约束）。
- 升级到新版本前先备份数据库，避免不可逆损失。

> 本文不披露具体迁移修订号、表/列计数、测试用例名与真实数据库文件路径；仅保留迁移纪律原则。
