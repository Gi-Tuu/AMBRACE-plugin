"""recipe_companion 插件入口。

在聊天中「自然已经出现吃饭语境」时，经 context_inject 注入离线食谱候选。

红线（务必保持）：
- 不注册 proactive_candidate、不新增饭点定时源、不抬高吃饭话题触发率；
- 纯离线、只读、内存态：不写文件、不联网、不启子进程、不引入网络套接字模块；
- permissions=[]：人设/记忆读取走 best-effort，未授权时 SDK 抛 PermissionError 被吞、零行为，
  将来补 persona:read / memory:read 即自动生效。
"""
from __future__ import annotations

import datetime as _dt
import random
import sys
from pathlib import Path

# importlib spec_from_file_location 加载时没有包上下文，先把自身目录插进 sys.path，
# 再以顶层模块方式导入同目录纯函数内核（不能写 ``from . import recipe_core``）。
_OWN_DIR = Path(__file__).resolve().parent
if str(_OWN_DIR) not in sys.path:
    sys.path.insert(0, str(_OWN_DIR))

import recipe_core as core  # noqa: E402

from app.plugins import sdk  # noqa: E402

try:
    from app.plugins.registry import EXAMPLE_DIR, USER_DIR  # noqa: E402
except Exception:  # pragma: no cover - 脱离内核环境时降级为空
    EXAMPLE_DIR = None
    USER_DIR = None

_index: core.RecipeIndex | None = None
_recent: core.RecentPicker | None = None

_DEFAULT_CFG = {
    "enabled": True,
    "suggest_top_n": 7,
    "recipe_top_n": 3,
    "explore_quota": 2,
    "inject_max_chars": 800,
    "quick_max_minutes": 20,
}


def _cfg() -> dict:
    cfg = dict(_DEFAULT_CFG)
    try:
        cfg.update(sdk.get_config() or {})
    except Exception:
        pass
    return cfg


def _ensure_index() -> core.RecipeIndex:
    global _index, _recent
    if _index is not None:
        return _index
    idx = core.RecipeIndex()
    # 扫描已安装的菜系分包（recipe-pack-*）目录合并数据（只读）
    pack_dirs: list = []
    for base in (EXAMPLE_DIR, USER_DIR):
        try:
            if base is not None and Path(base).is_dir():
                pack_dirs += [p for p in Path(base).iterdir()
                              if p.is_dir() and p.name.startswith("recipe-pack-")]
        except Exception:
            pass
    try:
        n = idx.load(_OWN_DIR, pack_dirs)
        sdk.log("recipe index loaded: %d dishes, coverage=%s", n, idx.coverage_report())
    except Exception as e:
        sdk.log("recipe index load failed: %s", e)
    _recent = core.RecentPicker()  # 进程内内存 LRU，不落盘
    _index = idx
    return _index


async def _gather_taste_texts(character_id) -> tuple[list, str]:
    """best-effort 取角色人设 + 记忆里的口味/忌口文本（只读端口）。

    未声明 persona:read / memory:read 时 SDK 抛 PermissionError，各自被独立 try/except 吞掉，
    返回空文本、零行为；将来补权限即自动生效。任何异常都绝不阻断主回复。
    """
    persona_text = ""
    mem_texts: list = []
    try:
        if character_id:
            p = await sdk.get_persona(int(character_id))
            persona_text = " ".join([str(p.get("personality") or ""),
                                     str(p.get("self_statement") or "")])
    except Exception as e:
        sdk.log("get_persona skipped: %s", e)
    try:
        if character_id:
            hits = await sdk.search_memory(
                int(character_id), "爱吃 口味 忌口 过敏 不吃 素食 清真 清淡 辣 甜食 食材",
                limit=8)
            mem_texts = [str(h.get("content") or "") for h in hits]
    except Exception as e:
        sdk.log("search_memory skipped: %s", e)
    return mem_texts, persona_text


def _today() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d")


def _current_hour() -> int:
    return _dt.datetime.now().hour


@sdk.hook("context_inject")
async def _on_context_inject(ctx: dict) -> None:
    try:
        cfg = _cfg()
        if not cfg.get("enabled", True):
            return
        user_msg = str(ctx.get("user_message") or "")
        idx = _ensure_index()
        if not idx.dishes:
            return  # 暂无菜品数据（数据由另一工序投放）：零注入、不报错
        scene = core.detect_scene(user_msg, _current_hour(), idx.lexicon)
        if not scene["is_food"]:
            return  # 非吃饭语境：零注入（不干扰、不抬话题）
        character_id = ctx.get("character_id")
        mem_texts, persona_text = await _gather_taste_texts(character_id)
        # 当前用户消息始终第一位：当句说"花生过敏/不吃辣/吃素/清真"即时硬过滤
        texts = [user_msg, persona_text, *mem_texts]
        rest = core.extract_restrictions(texts, idx.lexicon)
        prefs = core.extract_preferences(texts)
        rng = random.Random(f"{_today()}|{character_id}")  # 同日同角色稳定、跨日变化
        dishes = core.select_dishes(idx, scene, rest, prefs, cfg, user_msg,
                                    _today(), _recent, rng)
        if not dishes:
            ctx["context_messages"].append(
                {"role": "system", "content": core.format_empty(scene)})
            return
        ctx["context_messages"].append(
            {"role": "system", "content": core.format_inject(dishes, scene, rest, cfg)})
        _recent.remember(_today(), [d["id"] for d in dishes])
    except Exception as e:
        sdk.log("context_inject failed: %s", e)  # 全静默，绝不阻断主回复
