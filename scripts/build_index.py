"""CI 索引构建：扫描 plugins/ → 校验 → 打 zip 到 zips/ → 生成 index.json。

用法：
  python scripts/build_index.py plugins zips index.json
由 .github/workflows/build-index.yml 在 main 合并后调用。
"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from validate_plugin import check_plugin  # noqa: E402

# 仓库公开路径（index 里的下载地址指向 raw.githubusercontent 的 main 分支）
GITHUB_RAW = "https://raw.githubusercontent.com/{repo}/main/zips/{name}-{version}.zip"
REPO = "Gi-Tuu/AMBRACE-plugin"


def _ignore(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return any(p in ("__pycache__", ".git", ".venv") or p.endswith(".pyc") for p in parts)


def main() -> None:
    if len(sys.argv) < 4:
        print("用法: python scripts/build_index.py <plugins_dir> <zips_dir> <index_out>", file=sys.stderr)
        sys.exit(2)
    plugins_dir = Path(sys.argv[1])
    zips_dir = Path(sys.argv[2])
    index_out = Path(sys.argv[3])
    zips_dir.mkdir(parents=True, exist_ok=True)

    items = []
    for d in sorted(plugins_dir.iterdir()):
        if not (d / "manifest.json").is_file():
            continue
        errors = check_plugin(d)
        if errors:
            print(f"FAIL {d.name}: {errors}", file=sys.stderr)
            sys.exit(1)
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        name, version = m["name"], m["version"]
        zip_path = zips_dir / f"{name}-{version}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(d.rglob("*")):
                if f.is_file() and not _ignore(f.relative_to(d).as_posix()):
                    zf.write(f, f.relative_to(d).as_posix())
        sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        items.append({
            "name": name,
            "version": version,
            "description": m.get("description", ""),
            "author": m.get("author", ""),
            "category": m.get("category", "plugin"),
            "hooks": m.get("hooks", []),
            "permissions": m.get("permissions", []),
            "config": m.get("config", {}),
            "usage": m.get("usage", ""),
            "download_url": GITHUB_RAW.format(repo=REPO, name=name, version=version),
            "size": zip_path.stat().st_size,
            "sha256": sha,
            "min_api_version": m.get("min_api_version", "1.0"),
            "tags": [],
            "updated_at": "",
        })
        print(f"OK {name} v{version} ({zip_path.stat().st_size} bytes)")

    index = {"market": "AMBRACE 社区市场", "homepage": "https://github.com/AMBRACE-plugin", "updated_at": "", "items": items}
    index_out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"index.json: {len(items)} 个插件")


if __name__ == "__main__":
    main()