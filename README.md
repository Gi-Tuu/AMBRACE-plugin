# AMBRACE 插件市场（AMBRACE-plugin）

> 拥爱（AMBRACE）官方插件仓库。作者提交插件 → CI 自动校验 → 维护者人工审核 → 合并即上线。
> 仓库同时承载：
> - `index.json`：App 内「远程市场」直接读取的市场索引（raw.githubusercontent 免费直读）
> - `plugins/`：插件源码目录（PR 提交入口）
> - `zips/`：CI 自动生成的安装包（`<name>-<version>.zip`）

## 📚 开发文档

- [插件开发文档（完整版：manifest / 类型 / Hook / SDK / 权限 / 打包 / 调试）](docs/plugin-development.md)
- [扩展契约（扩展类型 / Hook / 权限 / SDK / 版本化承诺）](docs/extension-contract.md)

> 远程市场安装默认关闭，需管理员在服务端显式开启；插件权限在安装/升级前逐条确认。

## 目录结构

```
AMBRACE-plugin/
├── index.json              # 市场索引（CI 自动生成，勿手改）
├── plugins/                # 插件源码（作者 PR 提交位置）
│   └── <插件名>/
│       ├── manifest.json   # 插件声明（必填）
│       └── main.py         # 插件实现（必填）
├── zips/                   # 安装包（CI 生成，勿手传）
├── scripts/
│   └── validate_plugin.py  # 本地可复用的校验脚本
└── .github/workflows/
    ├── validate.yml        # PR 自动校验（manifest/权限/危险 API）
    └── build-index.yml     # 合并后自动生成 index.json + zips
```

## 插件作者：如何提交一个插件

1. **Fork 本仓库**，在 `plugins/` 下新建插件目录（目录名 = 插件名）。
2. 编写 `manifest.json` 与 `main.py`（参考 `plugins/` 内已有示例）。
3. 本地校验：`python scripts/validate_plugin.py plugins/<插件名>`（全部通过才可提交）。
4. 提交 PR：CI 会自动校验；**全部通过后由维护者人工 review 并 merge**。
5. 合并后 CI 自动生成 `zips/<name>-<version>.zip` 与 `index.json`，插件随即在 App「远程市场」可见。

## manifest.json 规范

```json
{
  "name": "weather_brief",
  "version": "1.0.0",
  "description": "给 AI 注入当天天气与出行建议",
  "author": "AMBRACE",
  "category": "plugin",
  "hooks": ["context_inject"],
  "permissions": [],
  "config": {"city": "auto"},
  "usage": "……",
  "min_api_version": "1.0"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| name | ✅ | 唯一；字母数字下划线，≤64 字符 |
| version | ✅ | 语义化版本（x.y.z） |
| description | ✅ | 一句话描述（≤200 字） |
| author | ✅ | 作者名 |
| category | `plugin` \| `mcp` |
| hooks | | 挂载点白名单（见下） |
| permissions | | 权限声明（涉及高危能力必须显式声明） |
| config | | 默认配置（JSON 对象） |
| min_api_version | | 最低服务端 API 版本（默认 1.0） |

### hooks 白名单

`context_inject`、`before_generate`、`after_generate`、`memory_written`、`memory_search`、`proactive_candidate`、`schedule_tick`、`http_router`

### permissions 可选值

`socket`、`send_message`、`http_request`、`network_upload`、`file_read`、`file_write`、`shell`、`device`、`camera`、`audio`、`location`、`contacts`、`storage`

## 审核规则（CI 自动执行 + 人工 review）

### CI 自动校验（validate.yml）

1. **manifest 校验**：字段合法、name/version/description/author 必填、version 语义化。
2. **hooks 白名单**：hooks 必须来自白名单，且与代码实际注册一致（sdk.hook 调用名必须已声明）。
3. **权限声明检查**：代码中出现 `subprocess`、`os.system`、`eval`、`exec`、`__import__`、`socket`、外传网络等敏感操作时，**必须在 manifest.permissions 显式声明**，否则不通过。
4. **危险 API 扫描**：禁止未声明的任意代码执行/网络外传；禁止混淆/加密代码。
5. **大小限制**：插件目录 ≤2MB、文件 ≤200 个；禁止二进制可执行文件（.exe/.dll/.so/.bin）。
6. **格式检查**：全部 `.py` 文件 UTF-8 可解析。

### 人工审核（维护者）

- CI 全绿后，维护者对插件代码进行 review（重点：数据外传、隐藏行为、恶意 hook）。
- 通过 → merge；有问题 → 在 PR 上反馈。

### 运行期护栏（App 侧）

- 安装 zip 前 sha256 校验（与 index.json 一致）。
- 解压前 manifest 复核 + 路径穿越/符号链接防护。
- 安装后可加载校验；失败自动回滚。
- 市场条目标注来源徽标 + 风险提示；远程安装前二次确认。

## 使用

- App 内：插件市场 → 右上角「远程市场」→ 添加本仓库索引地址 → 立即刷新。

```
https://raw.githubusercontent.com/Gi-Tuu/AMBRACE-plugin/main/index.json
```

## 协议

插件作者保留各自代码版权；提交即表示同意在本仓库内以 MIT 协议分发（可在 manifest 中声明其他许可）。