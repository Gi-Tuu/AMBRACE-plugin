"""recipe_companion · 食谱检索与推荐纯函数内核。

设计约束（re-ground 2026-10-01）：
- 零内核依赖、零网络、零子进程、零文件写入：仅用标准库，可独立 pytest；
- 场景识别 / 忌口提取 / 检索 / 去偏全部本地完成，零 LLM 调用；
- 过敏与明确忌口做硬过滤（安全优先：宁可不推，也不踩雷）；
- 多样性去偏：标签召回 + 偏好加权后按菜系分桶轮转 + 探索名额 + 进程内近期去重，
  避免反复推荐同一类菜；
- 两档输出：suggest（多道精简卡）/ recipe（少量带 3–5 步简化做法）；
- 注入块末尾自限长（inject_max_chars）。

注意：本模块刻意不写任何带括号的代码编译调用形式——市场静态扫描会把这种写法
判为危险 API，连编译型正则写法都会被误伤；这里干脆连正则都不用。
"""
from __future__ import annotations

import json
import random
from collections import defaultdict, deque
from pathlib import Path

# ───────────────────────────── 加载与索引 ─────────────────────────────


class RecipeIndex:
    """菜品索引：标签倒排 + 字符 bigram 倒排。一次性建内存索引，命中场景才检索。"""

    def __init__(self) -> None:
        self.dishes: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.tag_inverted: dict[str, set] = defaultdict(set)   # 标签值 -> 菜品下标
        self.bigram_inverted: dict[str, set] = defaultdict(set)  # 字符 bigram -> 菜品下标
        self.lexicon: dict = {}

    def load(self, own_dir: Path, extra_pack_dirs: list | None = None) -> int:
        """加载主包 data/recipes_*.json + 菜系分包 data/recipes/*.json（只读，不写盘）。"""
        files: list[Path] = []
        data_dir = Path(own_dir) / "data"
        if data_dir.is_dir():
            files += sorted(data_dir.glob("recipes_*.json"))
        for pack_dir in (extra_pack_dirs or []):
            pack_dir = Path(pack_dir)
            rd = pack_dir / "data" / "recipes"
            if rd.is_dir():
                files += sorted(rd.glob("*.json"))
            if (pack_dir / "data").is_dir():
                files += sorted((pack_dir / "data").glob("recipes_*.json"))
        for f in files:
            self._load_file(f)
        lex = data_dir / "tags_lexicon.json"
        if lex.is_file():
            try:
                self.lexicon = json.loads(lex.read_text(encoding="utf-8"))
            except Exception:
                self.lexicon = {}
        self._build_index()
        return len(self.dishes)

    def _load_file(self, path: Path) -> None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return  # 坏包跳过，不影响其它包
        for d in (payload.get("dishes") or []):
            if not self._valid(d):
                continue
            if d.get("id") in self.by_id:  # 同 id 去重（主包/分包重复）
                continue
            self.by_id[d["id"]] = d
            self.dishes.append(d)

    @staticmethod
    def _valid(d: dict) -> bool:
        for k in ("id", "name", "cuisine", "appearance", "taste", "ingredients", "steps"):
            if not d.get(k):
                return False
        if not isinstance(d.get("ingredients"), list) or not isinstance(d.get("steps"), list):
            return False
        return True

    def _build_index(self) -> None:
        self.tag_inverted.clear()
        self.bigram_inverted.clear()
        for i, d in enumerate(self.dishes):
            tag_values = []
            for key in ("cuisine", "staple", "temp"):
                if d.get(key):
                    tag_values.append(str(d[key]))
            for key in ("tags", "flavors", "methods", "slots", "diet", "season"):
                tag_values += [str(x) for x in (d.get(key) or [])]
            for ing in d.get("ingredients", []):
                tag_values.append(str(ing))
            for v in tag_values:
                self.tag_inverted[v].add(i)
            # 字符 bigram 倒排（菜名/别名/食材/长相/味道）：中文模糊匹配，零分词依赖
            blob = "".join(
                [str(d.get("name", ""))]
                + [str(x) for x in d.get("aliases", [])]
                + [str(x) for x in d.get("ingredients", [])]
                + [str(d.get("appearance", "")), str(d.get("taste", ""))]
            )
            for g in _bigrams(blob):
                self.bigram_inverted[g].add(i)

    def coverage_report(self) -> dict:
        rep: dict = {"total": len(self.dishes), "by_slot": defaultdict(int),
                     "by_diet": defaultdict(int), "by_cuisine": defaultdict(int),
                     "quick_le15": 0}
        for d in self.dishes:
            for s in d.get("slots", []):
                rep["by_slot"][s] += 1
            for s in d.get("diet", []):
                rep["by_diet"][s] += 1
            rep["by_cuisine"][d.get("cuisine", "?")] += 1
            try:
                if int(d.get("minutes", 999)) <= 15:
                    rep["quick_le15"] += 1
            except (TypeError, ValueError):
                pass
        return {k: (dict(v) if isinstance(v, defaultdict) else v) for k, v in rep.items()}


def _bigrams(text: str) -> list:
    """字符 bigram：先去掉所有空白字符（不依赖 re，避免 compile 扫描误伤）。"""
    text = "".join(ch for ch in str(text or "") if not ch.isspace())
    if len(text) < 2:
        return [text] if text else []
    return [text[i:i + 2] for i in range(len(text) - 1)]


# ───────────────────────────── 场景识别（本地零 LLM）─────────────────────────────


def _slot_from_hour(hour: int, lexicon: dict) -> str:
    hour = int(hour or 0)
    mapping = {"breakfast": "早餐", "brunch": "早午餐", "lunch": "午餐",
               "tea": "下午茶", "dinner": "晚餐", "midnight": "夜宵"}
    for slot, hours in (lexicon.get("slot_by_hour") or {}).items():
        try:
            if hour in list(hours):
                return mapping.get(slot, "晚餐")
        except TypeError:
            continue
    return "晚餐"


def _normalize_msg(msg: str) -> str:
    """轻量归一：去掉"一点/一点儿"这类修饰，让"一点辣都不吃 / 吃点什么"也能被召回。"""
    s = str(msg or "")
    s = s.replace("一点儿", "").replace("一点", "")
    return s


# 宽泛的"吃饭意图"词：覆盖自然语序（吃点什么好 / 晚上吃啥 / 有啥吃的 / 馋了 / 饿了…）
_EAT_INTENT = [
    "吃什么", "吃点什么", "吃啥", "吃点啥", "吃啥好", "吃点啥好",
    "有什么吃", "有啥吃", "啥吃的", "吃的", "吃点",
    "今晚吃", "晚上吃", "中午吃", "早上吃", "夜宵吃", "宵夜吃", "昨天吃",
    "做点吃", "做点什么吃", "点什么吃", "什么吃", "弄点吃",
    "下饭", "填肚子", "饿了", "肚子饿", "馋了", "想吃", "来点吃",
]


def detect_scene(user_message: str, hour: int, lexicon: dict) -> dict:
    """从用户消息 + 当前小时识别餐段/场景/口味/食材/模式。非吃饭语境返回 is_food=False。"""
    msg = _normalize_msg(user_message)
    scenes, flavors, ings = [], [], []
    sk = lexicon.get("scene_keywords") or {}
    for scene, kws in sk.items():
        if any(k in msg for k in kws):
            scenes.append(scene)
    for fl, kws in (lexicon.get("flavor_keywords") or {}).items():
        if any(k in msg for k in kws):
            flavors.append(fl)
    for ing, kws in (lexicon.get("ingredient_keywords") or {}).items():
        if any(k in msg for k in kws):
            ings.append(ing)
    is_recipe = any(k in msg for k in (lexicon.get("mode_recipe_keywords") or []))
    slot_words = ["早餐", "午饭", "午餐", "晚饭", "晚餐", "夜宵", "宵夜", "下午茶",
                 "吃什么", "吃啥", "点菜", "外卖", "做饭", "做菜", "菜谱", "食谱"]
    is_food = (bool(scenes)
               or any(w in msg for w in slot_words)
               or any(w in msg for w in _EAT_INTENT))
    return {
        "is_food": is_food,
        "mode": "recipe" if is_recipe else "suggest",
        "slot": _slot_from_hour(hour, lexicon),
        "scenes": scenes,
        "flavors": flavors,
        "ingredients": ings,
    }


# ─────────────────────── 忌口/过敏提取（硬过滤依据）───────────────────────
# 过敏 → 应排除的食材族
_ALLERGY_MAP = {
    "花生": ["花生"],
    "海鲜": ["虾", "蟹", "鱼", "鱿鱼", "扇贝", "海鲜"],
    "坚果": ["坚果", "杏仁", "腰果", "核桃"],
    "蛋": ["鸡蛋", "蛋黄"],
    "奶": ["牛奶", "奶酪", "芝士", "奶油", "黄油", "乳制品"],
    "麸质": ["面粉", "面条", "意面", "面筋"],
}


def extract_restrictions(texts: list, lexicon: dict) -> dict:
    """从一组文本里提取忌口食材、过敏、饮食偏好。

    texts 顺序：调用方务必把「当前用户消息」放第一位，保证当句说
    "花生过敏 / 不吃辣 / 我吃素 / 清真" 即时硬过滤；其后接人设/记忆文本。
    过敏为强信号（绝不推），饮食信仰/过敏相关为硬约束。

    两层规则取并集：
      1) 现有固定短语词表（restriction_keywords）；
      2) 子句内共现：同一子句里「过敏原/食材词 + 否定/医疗提示词」或「正向饮食提示词」，
         自然语序（"辣的我不吃" / "花生我过敏" / "牛肉我不吃"）也能召回。
    """
    blob = "\n".join(str(t or "") for t in (texts or []))
    rk = lexicon.get("restriction_keywords") or {}
    allergies, dislikes, diets = set(), set(), set()
    for item, kws in (rk.get("allergy") or {}).items():
        if any(k in blob for k in kws):
            allergies.add(item)
    for item, kws in (rk.get("dislike") or {}).items():
        if any(k in blob for k in kws):
            dislikes.add(item)
    for item, kws in (rk.get("diet") or {}).items():
        if any(k in blob for k in kws):
            diets.add(item)

    # —— 子句内共现（自然语序）——
    ca, cd, ck, cdiet = _clause_restrictions(blob)
    allergies |= ca
    dislikes |= cd
    banned_extra = ck
    diets |= cdiet

    banned_ingredients = set(dislikes)  # 忌口食材 → 直接黑名单（"不吃香菜"→含香菜剔除）
    for a in allergies:
        banned_ingredients.update(_ALLERGY_MAP.get(a, [a]))
    banned_ingredients |= banned_extra
    diet_constraints = set(diets)
    if "辣" in dislikes:
        diet_constraints.add("无辣")
    return {"allergies": allergies, "banned_ingredients": banned_ingredients,
            "diets": diet_constraints}


# 子句切分标点
_CLAUSE_SEPS = "，。！？,.!?；;、\n"
# 否定/医疗提示词（与食材词同子句出现才算忌口）
_NEG_CUES = ["过敏", "忌口", "忌", "不能吃", "不吃", "别放", "不要",
             "不爱吃", "讨厌", "碰不得", "一吃就"]
# 食材/过敏原词 → (过敏类, 黑名单食材列表, 忌口类名, diet 标签)
_CLAUSE_ING_RULES = [
    (["花生"], "花生", ["花生"], "花生", "无花生"),
    (["坚果", "核桃", "杏仁", "腰果", "开心果"], "坚果", ["坚果", "核桃", "杏仁", "腰果", "开心果"], "坚果", "无坚果"),
    (["海鲜", "虾", "蟹", "贝", "蚝", "鱼露", "虾酱"], "海鲜", ["海鲜", "虾", "蟹", "贝", "蚝", "鱼", "鱼露", "虾酱"], "海鲜", "无海鲜"),
    (["辣", "辣椒"], None, [], "辣", "无辣"),
    (["乳制品", "牛奶", "奶酪", "芝士", "奶油", "黄油"], None, [], "乳制品", "无乳制品"),
    (["鸡蛋", "蛋黄"], "蛋", ["鸡蛋", "蛋黄"], "蛋", "无蛋"),
    (["麸质", "小麦", "面粉"], None, ["面粉", "小麦"], "麸质", "无麸质"),
    (["牛肉"], None, ["牛肉"], "牛肉", None),
    (["猪肉", "五花", "排骨", "火腿", "培根", "腊肠"], "猪肉", ["猪肉", "五花", "排骨", "火腿", "培根", "腊肠"], "猪肉", None),
]
# 正向饮食提示词（无需否定词，子句内出现即成立）
_CLAUSE_POS_RULES = [
    (["纯素", "全素", "vegan"], "纯素", "素食"),
    (["吃素", "素食", "素的"], None, "素食"),
    (["清真", "halal"], None, "清真"),
    (["低糖", "无糖"], None, "低糖"),
    (["低卡", "减脂", "减肥", "控制热量"], None, "低卡"),
]


def _split_clauses(blob: str) -> list:
    s = str(blob or "").replace("一点儿", "").replace("一点", "")
    for p in _CLAUSE_SEPS:
        s = s.replace(p, "|")
    return [c.strip() for c in s.split("|") if c.strip()]


def _clause_restrictions(blob: str):
    """返回 (allergies, dislikes, banned_ingredients, diets)：子句内共现判定。"""
    allergies, dislikes, banned, diets = set(), set(), set(), set()
    for c in _split_clauses(blob):
        # 正向饮食提示（不依赖否定词）
        for words, diet_a, diet_b in _CLAUSE_POS_RULES:
            if any(w in c for w in words):
                if diet_a:
                    diets.add(diet_a)
                if diet_b:
                    diets.add(diet_b)
        has_neg = any(w in c for w in _NEG_CUES)
        if not has_neg:
            continue  # 无否定/医疗提示词 → "牛肉我爱吃"这类不产生忌口
        for words, allergy, ings, dislike, diet_label in _CLAUSE_ING_RULES:
            if not any(w in c for w in words):
                continue
            if allergy:
                allergies.add(allergy)
            if dislike:
                dislikes.add(dislike)
            banned.update(ings)
            if diet_label:
                diets.add(diet_label)
    return allergies, dislikes, banned, diets


# ─────────────────────── 偏好提取（软加权，非硬过滤）───────────────────────

_PREF_CUISINE_HINTS = {
    "川菜": ["川菜", "四川", "麻辣"], "粤菜": ["粤菜", "广东", "早茶"],
    "日本料理": ["日料", "日式", "寿司", "拉面", "和食"], "韩餐": ["韩餐", "韩式", "泡菜", "拌饭"],
    "泰国菜": ["泰餐", "泰国", "冬阴功"], "意大利餐": ["意面", "披萨", "意大利"],
}


def extract_preferences(texts: list) -> dict:
    """软偏好：爱吃的菜系/口味/食材（只加权，不锁定；去偏逻辑仍强制探索其它品类）。"""
    blob = "\n".join(str(t or "") for t in (texts or []))
    liked_cuisines, liked_flavors, liked_ings = set(), set(), set()
    for cuisine, kws in _PREF_CUISINE_HINTS.items():
        if any(k in blob for k in kws):
            liked_cuisines.add(cuisine)
    for fl, kws in {"辣": ["爱吃辣", "无辣不欢", "喜欢辣"], "甜": ["爱吃甜", "喜欢甜", "嗜甜"],
                    "清淡": ["口味清淡", "喜欢清淡"]}.items():
        if any(k in blob for k in kws):
            liked_flavors.add(fl)
    for ing, kws in {"鸡": ["爱吃鸡", "喜欢吃鸡", "鸡肉"], "鱼": ["爱吃鱼", "喜欢鱼"],
                    "豆腐": ["爱吃豆腐"], "面": ["爱吃面", "喜欢面食"],
                    "牛": ["爱吃牛肉", "喜欢牛排"]}.items():
        if any(k in blob for k in kws):
            liked_ings.add(ing)
    return {"cuisines": liked_cuisines, "flavors": liked_flavors, "ingredients": liked_ings}


# ───────────────────────────── 硬过滤 ─────────────────────────────

# 硬约束饮食标签：菜品必须显式打标，否则保守剔除（宁可不推，不可踩雷）
_HARD_DIET = {"纯素", "清真", "无海鲜", "无花生", "无坚果", "无麸质", "无乳制品", "无蛋"}


def _passes_hard_filter(d: dict, scene: dict, rest: dict, cfg: dict) -> bool:
    # 1) 过敏/忌口食材：命中任一食材即剔除（安全优先）
    ingredients = " ".join(str(x) for x in d.get("ingredients", []))
    for bad in rest.get("banned_ingredients", set()):
        if bad and bad in ingredients:
            return False
    # 2) 饮食偏好硬约束（信仰/过敏相关为硬；健康管理类软约束交给打分）
    dish_diets = set(d.get("diet", []))
    dish_flavors = " ".join(str(x) for x in d.get("flavors", []))
    for need in rest.get("diets", set()):
        if need == "素食":  # 素食/纯素都算满足素食
            if not ({"素食", "纯素"} & dish_diets):
                return False
        elif need == "无辣":  # 食材驱动优先：含任何辛辣食材即剔除；再看 flavors
            if _has_any(ingredients, _SPICY_ING):
                return False
            if "辣" in dish_flavors and "无辣" not in dish_diets:
                return False
        elif need in ("低糖", "低卡"):
            continue  # 软约束：不在此硬剔，交给 healthy 场景打分
        elif need in _HARD_DIET:
            if need not in dish_diets:
                return False
    # 3) 餐段：夜宵/早餐/下午茶这类强时段做硬过滤；午晚餐互通
    slot = scene.get("slot")
    if slot and d.get("slots") and slot not in d.get("slots", []):
        if slot in ("早餐", "夜宵", "下午茶"):
            return False
    # 4) 快手场景：时长上限
    if "quick" in scene.get("scenes", []):
        try:
            if int(d.get("minutes", 999)) > int(cfg.get("quick_max_minutes", 20)):
                return False
        except (TypeError, ValueError):
            return False
    return True


# ───────────────────── 打分 + 多样性选择（去偏核心）─────────────────────


def _score(d: dict, idx: int, scene: dict, prefs: dict,
           index: RecipeIndex, user_message: str) -> float:
    s = 0.0
    tag_map = {"cook": [], "order": [], "choose": [], "date": ["聚餐", "宴客"],
               "quick": ["快手", "简单"], "healthy": ["低卡", "清淡", "养胃"]}
    for sc in scene.get("scenes", []):
        for t in tag_map.get(sc, []):
            if idx in index.tag_inverted.get(t, set()):
                s += 3
    for fl in scene.get("flavors", []):
        if idx in index.tag_inverted.get(fl, set()):
            s += 4
    for ing in scene.get("ingredients", []):
        for ing_name in d.get("ingredients", []):
            if ing in str(ing_name) or str(ing_name) in ing:
                s += 5
    # 用户消息 bigram 命中（菜名/食材模糊匹配）
    for g in set(_bigrams(user_message)):
        if idx in index.bigram_inverted.get(g, set()):
            s += 0.6
    # 软偏好加权（只加分、不锁定）
    if d.get("cuisine") in prefs.get("cuisines", set()):
        s += 3
    if set(str(x) for x in d.get("flavors", [])) & prefs.get("flavors", set()):
        s += 2
    for ing in prefs.get("ingredients", set()):
        if any(ing in str(x) for x in d.get("ingredients", [])):
            s += 2
    # 难度/时长贴合（快手/健康场景偏好简单）
    if "quick" in scene.get("scenes", []):
        try:
            s += max(0.0, (25 - int(d.get("minutes", 25))) * 0.2)
        except (TypeError, ValueError):
            pass
    return s


class RecentPicker:
    """近期去重：进程内内存 LRU（按日分桶）。不落盘——跨重启去重丢失（README 已说明）。"""

    def __init__(self, cap_per_day: int = 60) -> None:
        self.cap = cap_per_day
        self._seen: dict = defaultdict(lambda: deque(maxlen=cap_per_day))

    def contains(self, day: str, dish_id: str) -> bool:
        return dish_id in self._seen[day]

    def remember(self, day: str, dish_ids: list) -> None:
        q = self._seen[day]
        for i in dish_ids:
            q.append(i)


def select_dishes(index: RecipeIndex, scene: dict, rest: dict, prefs: dict,
                  cfg: dict, user_message: str, day: str,
                  recent: RecentPicker, rng: random.Random | None = None) -> list:
    """硬过滤 → 打分 → 多样性分桶轮转 + 探索名额 + 近期去重，返回 Top-N。"""
    rng = rng or random.Random()
    mode = scene.get("mode", "suggest")
    n = int(cfg.get("recipe_top_n", 3)) if mode == "recipe" else int(cfg.get("suggest_top_n", 7))
    explore = int(cfg.get("explore_quota", 2))
    # 1) 硬过滤
    pool = [(i, d) for i, d in enumerate(index.dishes) if _passes_hard_filter(d, scene, rest, cfg)]
    # 2) 打分
    scored = [(_score(d, i, scene, prefs, index, user_message), i, d) for i, d in pool]
    scored.sort(key=lambda x: x[0], reverse=True)
    # 3) 多样性分桶：按 cuisine 分桶，轮转从每桶取当前最高分
    buckets: dict = defaultdict(list)
    for item in scored:
        buckets[item[2].get("cuisine", "?")].append(item)
    for k in buckets:
        buckets[k].sort(key=lambda x: x[0], reverse=True)
    pref_cuisines = prefs.get("cuisines", set())
    chosen: list = []
    chosen_ids: set = set()

    def _take(from_buckets: list, prefer_unseen: bool) -> None:
        order = list(from_buckets)
        rng.shuffle(order)
        for c in order:
            if len(chosen) >= n:
                return
            while buckets.get(c):
                sc, i, d = buckets[c][0]
                if d["id"] in chosen_ids:
                    buckets[c].pop(0)
                    continue
                if prefer_unseen and recent.contains(day, d["id"]) \
                        and sum(len(v) for v in buckets.values()) > n:
                    buckets[c].pop(0)  # 近期推过且池子还够，换别的
                    continue
                buckets[c].pop(0)
                chosen.append(d)
                chosen_ids.add(d["id"])
                break

    # 4a) 先填偏好菜系（但不超过 n-explore，给探索留名额）
    pref_list = [c for c in buckets if c in pref_cuisines]
    other_list = [c for c in buckets if c not in pref_cuisines]
    pref_quota = max(0, n - explore)
    _take(pref_list, True)
    del chosen[pref_quota:]  # 超出偏好配额的丢弃（已从桶里 pop，不会回灌）
    chosen_ids = {d["id"] for d in chosen}
    # 4b) 探索名额：强制从非偏好菜系取（去偏关键，避免信息茧房）
    _take(other_list, True)
    # 4c) 还不够则跨桶补齐（兜底，保证不空）
    if len(chosen) < n:
        _take(list(buckets.keys()), True)
    return chosen[:n]


# ─────────────── 注入格式化（两档 + 去偏指令 + 自我限长）───────────────


def format_inject(dishes: list, scene: dict, rest: dict, cfg: dict) -> str:
    mode = scene.get("mode", "suggest")
    max_chars = int(cfg.get("inject_max_chars", 800))
    head = ("【食谱参考·离线菜谱】用户此刻在聊吃的，下面是结合餐段/场景与双方口味筛出的候选"
            "（事实素材，不是要你照念）：\n")
    lines = []
    if mode == "recipe":
        for d in dishes:
            steps = " → ".join(str(x) for x in d.get("steps", [])[:4])
            lines.append(
                f"· {d['name']}（{d.get('cuisine', '')}，{d.get('minutes', '?')}分钟，"
                f"难度{d.get('difficulty', '?')}/3）食材：{'、'.join(str(x) for x in d.get('ingredients', [])[:8])}；"
                f"{d.get('taste', '')}；简化做法：{steps}")
    else:
        for d in dishes:
            lines.append(
                f"· {d['name']}（{d.get('cuisine', '')}）：{d.get('appearance', '')}；"
                f"味道{d.get('taste', '')}；主要食材{'、'.join(str(x) for x in d.get('ingredients', [])[:6])}；"
                f"标签：{'/'.join([str(x) for x in (d.get('tags', []) + d.get('flavors', []))[:5]])}")
    tail = ("\n用法：像本人自然聊吃的那样从中挑或结合着说，可报菜名、描述长相味道、给一两句做法；"
            "不要整段罗列、不要说“根据菜谱”；请在不同菜系/品类间换着推荐，不要总停在同一类；"
            "若用户问具体做法再给步骤；用户忌口/过敏的食材一律不要出现。")
    if rest.get("allergies"):
        tail += f"（已为你硬过滤过敏项：{'、'.join(sorted(rest['allergies']))}）"
    text = head + "\n".join(lines) + tail
    return text[:max_chars]


def format_empty(scene: dict) -> str:
    return ("【食谱参考】当前没有同时满足餐段与忌口条件的离线菜品，不要硬报菜名；"
            "可泛泛给方向或建议用户放宽条件（如时段/时长/忌口），不要编造不存在于候选里的具体菜。")


# ═══════════════ 食材→餐段/忌口 权威推导（依据完整食材表，不信基线标签）═══════════════
#
# 背景：基线菜品的 diet/slots 是规则引擎一刀切的默认值（几乎每道菜都标了 午餐/晚餐/
# 无花生/无坚果，还把大量辣菜标成“无辣”、把含猪肉/酒的菜标成“清真”）。硬过滤要可信，
# 忌口与餐段必须依据「完整食材表 + 做法 + 菜名」重新推导。
# 全部用子串包含判定（不用编译型正则），纯标准库、只读、内存态。


def _has_any(blob: str, words) -> bool:
    return any(w in blob for w in words)


# 食材分类词表（子串包含即可命中；取词时避开“鸡蛋/蛋糕”这类误命中，鸡肉用带后缀的具体词）
_PORK = ["猪肉", "五花", "排骨", "猪油", "火腿", "培根", "腊肠", "叉烧", "肉酱",
         "明胶", "gelatin", "金华火腿"]
_BEEF = ["牛肉", "牛排", "牛腩", "牛腱", "肥牛", "牛骨", "牛尾", "牛舌"]
_LAMB = ["羊肉", "羊排", "羊腿", "烤羊", "羊羔"]
_POULTRY = ["鸡肉", "鸡腿", "鸡胸", "鸡翅", "鸡块", "鸡丁", "鸭肉", "鸭胸",
            "烤鸭", "鹅肉", "鹌鹑", "鸽"]
_SEAFOOD = ["鱼", "虾", "蟹", "贝", "蚝", "鱿", "墨鱼", "章鱼", "鲍鱼", "干贝", "海参",
            "龙虾", "带鱼", "黄鱼", "三文鱼", "金枪鱼", "鳗鱼", "牡蛎", "蛤蜊", "扇贝",
            "蚝油", "鱼露", "虾酱", "蚵", "蛏"]
_EGG = ["鸡蛋", "蛋黄", "蛋清", "皮蛋", "咸蛋", "蛋黄酱", "蛋液", "蛋皮"]
_DAIRY = ["牛奶", "黄油", "奶油", "淡奶油", "奶酪", "芝士", "酸奶", "奶粉",
          "淡奶", "植脂淡奶", "炼乳", "马苏里拉", "马斯卡彭"]
_PEANUT = ["花生", "花生酱"]
_NUT = ["腰果", "杏仁", "核桃", "碧根果", "开心果", "栗子", "榛子", "松子", "夏威夷果"]
_GLUTEN = ["小麦", "面粉", "面条", "面包", "饺子皮", "面包糠", "大麦", "黑麦",
           "酱油", "挂面", "意面", "拉面", "面皮", "烤麸", "水饺皮"]
_ALCOHOL = ["料酒", "黄酒", "白酒", "红酒", "啤酒", "香槟", "朗姆", "利口",
            "酒酿", "米酒", "葡萄酒", "味醂", "味啉"]
_SPICY_ING = ["辣椒", "干辣椒", "小米辣", "剁椒", "郫县豆瓣", "辣椒粉", "花椒",
              "火锅底料", "辣酱", "辣椒酱", "甜辣酱", "辣油", "辣椒油",
              "朝天椒", "尖椒", "泡椒"]
_SUGAR = ["白糖", "冰糖", "蜂蜜", "甜面酱", "红糖", "白砂糖", "果酱", "糖浆", "焦糖"]
_BREAKFAST_WORDS = ["粥", "包子", "烧卖", "肠粉", "糯米鸡", "凤爪", "煎饼", "吐司",
                    "可颂", "欧姆蛋", "松饼", "麦片", "豆浆", "早午餐", "油条",
                    "豆腐脑", "胡辣汤", "蛋饼", "粢饭",
                    # 亚洲汤粉面常作早餐（用具体名，避免把"炒河粉/干炒牛河"误判为早餐）
                    "热干面", "刀削面", "油泼面", "葱油拌面", "片儿川", "牛肉面",
                    "茶泡饭", "泡饭", "越南法包", "越南牛肉河粉", "越南烤肉米粉"]
_DESSERT_WORDS = ["蛋糕", "马卡龙", "布丁", "冰淇淋", "派", "司康", "和菓子", "糖饼",
                  "奶昔", "奶茶", "慕斯", "曲奇", "饼干", "提拉米苏", "甜品",
                  "蛋挞", "泡芙", "甜饮", "舒芙蕾",
                  # 甜饮与小食
                  "咖啡", "酸奶", "可乐饼", "咖喱角", "鱿鱼圈", "奶冻", "奶油卷",
                  "大福", "铜锣烧", "樱饼", "最中", "芒果糯米饭", "鲷鱼烧",
                  "闪电泡芙", "苹果挞"]
_LATENIGHT_WORDS = ["烧烤", "炸鸡", "串", "卤味", "烤肉", "泡面", "烤肠", "玉米片",
                    "小龙虾", "夜宵",
                    # 火锅/麻辣香锅、大排档快炒、煎烤小食
                    "火锅", "铁锅炖", "麻辣香锅", "炒饭", "炒面", "炒河粉", "炒粉",
                    "炒空心菜", "煎饺", "小丸子", "辣炒年糕", "部队锅", "热狗",
                    "烤玉米", "唐杜里", "烤鸡", "法吉塔", "烤哈罗米"]
_SAVORY_METHODS = ["炒", "烧", "炖", "煎", "煮", "烤", "蒸", "炸", "烩", "卤", "拌"]
_SPICY_FLAVORS = ["麻辣", "香辣", "酸辣", "微辣", "辣"]


def _ing_blob(rec: dict) -> str:
    return " ".join(str(x) for x in rec.get("ingredients", [])) + " " + str(rec.get("name", ""))


def _flavor_blob(rec: dict) -> str:
    return " ".join(str(x) for x in rec.get("flavors", []))


def _is_vegan_violating(blob: str) -> bool:
    """纯素违规：含任何肉/海鲜/蛋/奶/蜂蜜等动物源。"""
    return (_has_any(blob, _PORK) or _has_any(blob, _BEEF) or _has_any(blob, _LAMB)
            or _has_any(blob, _POULTRY) or _has_any(blob, _SEAFOOD)
            or _has_any(blob, _EGG) or _has_any(blob, _DAIRY)
            or _has_any(blob, ["蜂蜜"]))


def derive_slots(rec: dict) -> list:
    """依据 name/ingredients/methods/tags/temp/staple 推导餐段（不信基线 slots）。

    - 咸鲜正餐主菜（配饭/面/饼，或蛋白+蔬，经炒烧炖煎煮烤）→ 午餐 + 晚餐；
    - 早餐信号（粥/包子/早茶/煎饼/吐司/松饼/豆浆等）→ 早餐；汤面/粉面类可兼午餐；
    - 甜品/蛋糕/布丁/冰淇淋/甜饮/奶昔等 → 下午茶（不当成午晚餐）；
    - 夜宵信号（烧烤/炸鸡/串/卤味/烤肉/泡面等）→ 夜宵。
    """
    name = str(rec.get("name", ""))
    ing = " ".join(str(x) for x in rec.get("ingredients", []))
    tags = " ".join(str(x) for x in rec.get("tags", []))
    methods = " ".join(str(x) for x in rec.get("methods", []))
    blob = name + " " + ing + " " + tags + " " + methods

    is_dessert = _has_any(blob, _DESSERT_WORDS)
    is_breakfast = _has_any(blob, _BREAKFAST_WORDS)
    is_latenight = _has_any(blob, _LATENIGHT_WORDS)
    is_savory_main = (_has_any(methods, _SAVORY_METHODS)
                      or _has_any(blob, ["盖饭", "炒饭", "汤面", "拉面", "拌面"]))

    if is_dessert:
        return ["下午茶"]
    if is_breakfast:
        slots = ["早餐"]
        if _has_any(blob, ["面", "粉", "汤面"]):  # 汤面/粉面类早餐可兼午餐
            slots.append("午餐")
        return slots
    slots = []
    if is_savory_main:
        slots += ["午餐", "晚餐"]
    if is_latenight:
        slots.append("夜宵")
    return slots or ["午餐", "晚餐"]


def derive_diets(rec: dict) -> list:
    """依据完整食材表推导受控 diet 标签（不信基线 diet）。

    受控值：素食 / 纯素 / 清真 / 无辣 / 无海鲜 / 无花生 / 无坚果 / 无麸质 / 无乳制品 /
    无蛋 / 低糖 / 低卡。
    """
    blob = _ing_blob(rec)
    flavors = _flavor_blob(rec)
    tags = " ".join(str(x) for x in rec.get("tags", []))
    methods = " ".join(str(x) for x in rec.get("methods", []))

    has_pork = _has_any(blob, _PORK)
    has_meat = (has_pork or _has_any(blob, _BEEF) or _has_any(blob, _LAMB)
                or _has_any(blob, _POULTRY))
    has_seafood = _has_any(blob, _SEAFOOD)
    has_egg = _has_any(blob, _EGG)
    has_dairy = _has_any(blob, _DAIRY)
    has_peanut = _has_any(blob, _PEANUT)
    has_nut = _has_any(blob, _NUT)
    has_gluten = _has_any(blob, _GLUTEN)
    has_alcohol = _has_any(blob, _ALCOHOL) or _has_any(blob, ["明胶", "gelatin"])
    has_spicy_ing = _has_any(blob, _SPICY_ING)
    has_spicy_flavor = _has_any(flavors, _SPICY_FLAVORS)
    has_sugar = _has_any(blob, _SUGAR)
    is_dessert = _has_any(blob + " " + tags, _DESSERT_WORDS)

    diet = []
    # 纯素：无肉/海鲜/蛋/奶/蜂蜜
    if not has_meat and not has_seafood and not has_egg and not has_dairy and not _has_any(blob, ["蜂蜜"]):
        diet.append("纯素")
    # 素食：无肉/海鲜（蛋奶可）
    if not has_meat and not has_seafood:
        diet.append("素食")
    # 清真：无猪肉及衍生、无酒/含酒、无明胶/猪油；允许牛羊鸡鱼蛋奶植物
    if not has_pork and not has_alcohol:
        diet.append("清真")
    # 无辣：无辛辣食材且 flavors 不含 麻辣/香辣/酸辣/微辣
    if not has_spicy_ing and not has_spicy_flavor:
        diet.append("无辣")
    if not has_seafood:
        diet.append("无海鲜")
    if not has_peanut:
        diet.append("无花生")
    if not has_nut:
        diet.append("无坚果")
    if not has_gluten:
        diet.append("无麸质")
    if not has_dairy:
        diet.append("无乳制品")
    if not has_egg:
        diet.append("无蛋")
    # 低糖：无添加糖/蜂蜜、非甜品甜饮
    if not has_sugar and not is_dessert:
        diet.append("低糖")
    # 低卡（保守）：清蒸/煮/凉拌/清炒或沙拉/清淡标签，且非油炸、无重糖重油、非甜品
    light = (_has_any(methods, ["蒸", "煮", "凉拌", "清炒", "清蒸"])
             or _has_any(tags, ["沙拉", "减脂", "健身", "清淡", "清汤"]))
    not_heavy = not _has_any(blob, ["炸", "奶油", "糖"]) and not is_dessert
    if light and not_heavy:
        diet.append("低卡")
    return diet


def find_contradictions(rec: dict) -> list:
    """返回「基线 diet 标签 vs 实际食材」的矛盾（供门禁/数据清洗用）。"""
    blob = _ing_blob(rec)
    flavors = _flavor_blob(rec)
    base = set(rec.get("diet", []))
    issues = []

    has_pork = _has_any(blob, _PORK) or _has_any(blob, ["明胶", "gelatin", "猪油"])
    has_alcohol = _has_any(blob, _ALCOHOL)
    has_spicy = _has_any(blob, _SPICY_ING) or _has_any(flavors, _SPICY_FLAVORS)
    has_seafood = _has_any(blob, _SEAFOOD)
    has_meat = (has_pork or _has_any(blob, _BEEF) or _has_any(blob, _LAMB)
                or _has_any(blob, _POULTRY) or has_seafood)
    has_dairy = _has_any(blob, _DAIRY)
    has_gluten = _has_any(blob, _GLUTEN)
    has_peanut = _has_any(blob, _PEANUT)
    has_nut = _has_any(blob, _NUT)
    has_egg = _has_any(blob, _EGG)

    if "清真" in base and (has_pork or has_alcohol):
        issues.append("标清真但含猪肉/衍生/酒/明胶")
    if "无辣" in base and has_spicy:
        issues.append("标无辣但含辣椒/花椒或辣味 flavor")
    if ("素食" in base or "纯素" in base) and has_meat:
        issues.append("标素食/纯素但含肉或海鲜")
    if "无乳制品" in base and has_dairy:
        issues.append("标无乳制品但含奶制品")
    if "无麸质" in base and has_gluten:
        issues.append("标无麸质但含麸质谷物/酱油")
    if "无花生" in base and has_peanut:
        issues.append("标无花生但含花生")
    if "无坚果" in base and has_nut:
        issues.append("标无坚果但含树坚果")
    if "无蛋" in base and has_egg:
        issues.append("标无蛋但含蛋")
    if "无海鲜" in base and has_seafood:
        issues.append("标无海鲜但含海鲜")
    return issues
