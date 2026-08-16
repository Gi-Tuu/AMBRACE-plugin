"""插件提交校验脚本：manifest / hooks 白名单 / 权限声明 / 危险 API / 大小限制。

用法：
  python scripts/validate_plugin.py plugins/<插件名>        # 校验单个插件
  python scripts/validate_plugin.py plugins                 # 校验全部插件
退出码 0 = 通过；非 0 = 校验失败（stderr 打印原因）。
CI（validate.yml）直接调用本脚本，本地作者也可先跑一遍。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOOKS_WHITELIST = {
    "context_inject", "before_generate", "after_generate",
    "memory_written", "memory_search", "proactive_candidate",
    "schedule_tick", "http_router",
}
PERMISSIONS_ALLOWED = {
    "socket", "send_message", "http_request", "network_upload",
    "file_read", "file_write", "shell", "device", "camera",
    "audio", "location", "contacts", "storage",
}
MAX_SIZE = 2 * 1024 * 1024  # 2MB
MAX_FILES = 200
BANNED_EXT = {".exe", ".dll", ".so", ".bin", ".dylib"}
# 敏感操作 → 需要声明的权限（未声明即失败）
SENSITIVE_PATTERNS = {
    "shell": re.compile(r"\b(subprocess|os\.system|os\.popen|popen)\b"),
    "socket": re.compile(r"\bimport\s+socket\b|\bsocket\.socket\b"),
    "network_upload": re.compile(r"\b(requests\.(post|put|patch|delete)|urllib\.request|http\.client|aiohttp)\b"),
    "file_write": re.compile(r"\b(open\([^)]*[\"']w|write_bytes|write_text|shutil\.(copy|move|rmtree))\b"),
}
# 绝对禁止（无论声明与否）
FORBIDDEN = re.compile(r"\b(eval|exec|__import__|compile)\s*\(")


def check_manifest(path: Path) -> list[str]:
    errors = []
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"manifest.json 解析失败: {e}"]
    if not isinstance(m, dict):
        return ["manifest.json 必须是 JSON 对象"]
    for field in ("name", "version", "description", "author"):
        if not m.get(field):
            errors.append(f"缺必填字段: {field}")
    name = str(m.get("name", ""))
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
        errors.append(f"name 非法（须字母数字下划线 ≤64）: {name!r}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(m.get("version", ""))):
        errors.append(f"version 必须是语义化版本 x.y.z: {m.get('version')!r}")
    if len(str(m.get("description", ""))) > 200:
        errors.append("description 超过 200 字")
    cat = m.get("category", "plugin")
    if cat not in ("plugin", "mcp"):
        errors.append(f"category 非法: {cat!r}")
    hooks = m.get("hooks", [])
    if not isinstance(hooks, list):
        errors.append("hooks 必须是数组")
    else:
        for h in hooks:
            if h not in HOOKS_WHITELIST:
                errors.append(f"hook 不在白名单: {h!r}")
    perms = m.get("permissions", [])
    if not isinstance(perms, list):
        errors.append("permissions 必须是数组")
    else:
        for p in perms:
            if p not in PERMISSIONS_ALLOWED:
                errors.append(f"权限不在允许列表: {p!r}")
    if not isinstance(m.get("config", {}), dict):
        errors.append("config 必须是对象")
    return errors


def check_plugin(plugin_dir: Path) -> list[str]:
    errors = []
    files = [f for f in plugin_dir.rglob("*") if f.is_file()]
    if len(files) > MAX_FILES:
        errors.append(f"文件数超过 {MAX_FILES}: {len(files)}")
    total = sum(f.stat().st_size for f in files)
    if total > MAX_SIZE:
        errors.append(f"目录超过 {MAX_SIZE // 1024 // 1024}MB: {total}")
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.is_file():
        return ["缺 manifest.json"]
    errors += check_manifest(manifest_path)

    # 危险 API 静态扫描
    declared = set(json.loads(manifest_path.read_text(encoding="utf-8")).get("permissions", []))
    py_files = [f for f in files if f.suffix == ".py"]
    for f in py_files:
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:
            errors.append(f"文件非 UTF-8: {f.relative_to(ROOT)}")
            continue
        if FORBIDDEN.search(src):
            errors.append(f"禁止的代码执行 API（eval/exec/__import__/compile）: {f.name}")
        for perm, pat in SENSITIVE_PATTERNS.items():
            if pat.search(src) and perm not in declared:
                errors.append(
                    f"检测到敏感操作但未声明权限 [{perm}]: {f.name}"
                )
    # 禁止二进制可执行文件
    for f in files:
        if f.suffix.lower() in BANNED_EXT:
            errors.append(f"禁止二进制可执行文件: {f.relative_to(ROOT)}")
    return errors


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "plugins"
    if not target.is_dir():
        print(f"目录不存在: {target}", file=sys.stderr)
        sys.exit(2)
    if (target / "manifest.json").is_file():
        dirs = [target]
    else:
        dirs = sorted(p for p in target.iterdir() if p.is_dir() and (p / "manifest.json").is_file())
    if not dirs:
        print("未找到插件（plugins 下需有含 manifest.json 的目录）", file=sys.stderr)
        sys.exit(2)
    all_ok = True
    base = target.resolve()
    for d in dirs:
        errors = check_plugin(d)
        rel = d.resolve().relative_to(base) if d.resolve().is_relative_to(base) else d.name
        if errors:
            all_ok = False
            print(f"FAIL {rel}:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
        else:
            print(f"OK   {rel}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()