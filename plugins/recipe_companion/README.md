# 食谱伴侣 recipe_companion（离线插件）

纯离线、只读、内存态的食谱推荐插件。聊天中**已经自然出现吃饭话题**时，经 `context_inject`
注入离线菜品候选（精简卡 / 带简化步骤），不主动制造吃饭话题、不抬高触发率。

## 文件

```
code/
├── manifest.json          # 插件声明（hooks=context_inject, permissions=[]）
├── main.py                # 插件入口：context_inject hook
├── recipe_core.py        # 纯函数内核（索引/识别/过滤/打分/去偏/格式化，仅依赖标准库）
├── README.md
└── tests/test_recipe_core.py
```

菜品数据由另一工序投放到 `data/recipes_*.json`（本包不含数据）。

## 权限与合规

- `permissions: []`：不申请任何权限。本插件纯离线、只读、内存计算即可工作。
- 人设/记忆读取（`sdk.get_persona` / `sdk.search_memory`）以 best-effort 方式调用：
  未声明 `persona:read` / `memory:read` 时 SDK 抛 `PermissionError`，被独立 try/except 吞掉，
  零行为；将来补权限即自动生效。
- 忌口/过敏**以当前用户消息为主**提取：当句说「花生过敏 / 不吃辣 / 我吃素 / 清真」即时硬过滤。
- 不写文件、不联网、不启子进程、不引入网络套接字模块；代码不含动态代码执行类调用。

## 行为

- **两档注入**：
  - `suggest`（吃什么/点菜/外卖/夜宵）：多道精简卡（菜名+菜系+长相味道+主要食材+标签）；
  - `recipe`（怎么做/做法/步骤）：少量带 3–5 步简化做法。
- **多样性去偏**：标签召回 + 偏好加权后按菜系分桶轮转，保留探索名额（`explore_quota`），
  避免反复推同一类菜。
- **近期去重**：进程内内存 LRU，避免连续两轮推同样的菜。
  ⚠️ **不落盘**：插件重启后近期去重状态丢失（这是零权限、只读、不写盘设计的取舍）。
- **自我限长**：注入块末尾截断到 `inject_max_chars`（默认 800 字）。
- **非吃饭语境零注入**：不相关对话不 append 任何食谱块。

## 配置（config）

| 键 | 默认 | 含义 |
|---|---|---|
| enabled | true | 总开关 |
| suggest_top_n | 7 | suggest 档推荐数量 |
| recipe_top_n | 3 | recipe 档推荐数量 |
| explore_quota | 2 | 强制非偏好菜系的探索名额 |
| inject_max_chars | 800 | 注入块字数上限 |
| quick_max_minutes | 20 | 快手场景时长上限（分钟） |

## 红线

- 不注册 `proactive_candidate`；不新增饭点定时源；不抬高吃饭话题触发率。
- 仅在已自然出现的吃饭语境里注入。

## 测试

```
D:\AMBRACE\backend\.venv\Scripts\python.exe -m pytest tests -q
```

`recipe_core.py` 仅依赖标准库，可用任意 Python 3.10+ 独立运行。

## 免责

推荐仅供参考；严重过敏请自行核对食材，本插件不提供营养/医疗建议。
