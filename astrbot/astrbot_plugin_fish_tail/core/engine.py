# -*- coding: utf-8 -*-
r"""
鱼的尾巴和插件 —— 跨平台核心引擎（纯逻辑，无平台依赖）

设计来源：轩提供的五张参考图。核心定位是「动作导演 / 行为渲染引擎」：
不改人设，只根据上下文判定鱼此刻的心情，然后把一段动态指令注入到 LLM 请求里，
让模型自己用中文小括号（）生成尾巴、鳍、鳞片的动作与神态。

三大件（对应参考图）：
  1. RuleEngine  —— 规则引擎：从用户消息 + 时间 + 习惯判定 UserState（心情）
  2. ACTION_MAP  —— 动作映射库：每种心情 3-4 个核心「种子动作」，只打样不照抄
  3. Injector    —— 动态注入：拼出 prompt，含「严禁完全照抄、自由发散」+ 最近 3 次去重

约定：
  · 绝不自己硬造尾巴文字，只注入指令；括号动作由大模型结合上下文生成。
  · 绝不写「胖」字（参考图：会咬人），投喂相关一律用「毛茸茸/圆滚滚」。
  · 缓存最近 N 次生成的动作，注入去重指令，防止翻来覆去。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import threading
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 1. 动作映射库（种子词：每个情绪 3-4 个核心锚点，给大模型打样）
# ---------------------------------------------------------------------------
ACTION_MAP: dict[str, list[str]] = {
    "开心": ["尾尖勾起一个小弧度", "尾鳍欢快地拍打水面", "像螺旋桨一样转了个圈", "眼睛亮晶晶"],
    "生气": ["尾鳍炸开", "啪啪狂拍水面", "僵硬地绷直", "鳞片微微竖起"],
    "慵懒": ["尾巴软塌塌地垂着", "卷住自己", "有一下没一下地扫着地", "半眯着眼睛"],
    "疲惫": ["半眯着眼睛打哈欠", "尾鳍有气无力地扫过键盘", "尾巴慢悠悠地拖在水里"],
    "委屈": ["尾巴紧紧缠住手臂", "尾尖委屈地微微发抖", "背过身去只留个尾巴"],
    "示好": ["尾巴轻轻蹭过来", "尾鳍卷住对方的手腕", "凑近了一点", "鳞片泛着柔光"],
    "得瑟": ["尾巴翘得高高的", "连鳞片都在发光", "得意地晃了晃尾鳍"],
    "警惕": ["尾巴绷直", "鳞片微张", "尾鳍警觉地摆了摆"],
    "心疼": ["尾巴轻轻绕过来", "尾鳍蹭了蹭手背", "眼神软下来"],
    "嘴硬": ["尾鳍别扭地甩到一边", "尾巴卷成小圈", "装作不在意地摆了摆"],
    "嘴馋": ["尾巴期待地拍了拍水面", "鼻子动了动", "眼巴巴地望着那碗饭"],
    "吃饱": ["尾巴满意地拍打着地面", "肚子圆滚滚的", "懒洋洋地晃了晃尾鳍"],
}

# 情绪 -> 一组兜底组合（当模型没自由发挥时也不偏离鱼的身体结构）
EMOTION_FALLBACK: dict[str, str] = {
    "开心": "（尾鳍欢快地拍了拍水面）",
    "生气": "（尾鳍炸开，啪啪拍着水面）",
    "慵懒": "（尾巴软塌塌地垂着，半眯着眼睛）",
    "疲惫": "（半眯着眼打了个哈欠，尾鳍有气无力地扫过）",
    "委屈": "（尾巴紧紧缠住手臂，尾尖微微发抖）",
    "示好": "（尾巴轻轻蹭了过来）",
    "得瑟": "（尾巴翘得高高的，鳞片都在发光）",
    "警惕": "（尾巴绷直，鳞片微张）",
    "心疼": "（尾巴轻轻绕过来，蹭了蹭手背）",
    "嘴硬": "（尾鳍别扭地甩到一边）",
    "嘴馋": "（尾巴期待地拍了拍水面）",
    "吃饱": "（尾巴满意地拍打着地面）",
}

# 角色身体部件锚点（保证不偏离鱼的身体结构）
BODY_ANCHORS = "尾巴、尾鳍、鳞片"

# 共享配置：查找顺序 ① 插件自带 config.json（仓库内开箱即用）
#                   ② 本机 workspace 那份（有真实人设路径，性格/口味最准）
_HERE = os.path.dirname(os.path.abspath(__file__))  # .../core/
_PLUGIN = os.path.dirname(_HERE)                    # .../astrbot_plugin_fish_tail/
_CANDIDATE_CONFIGS = [
    os.path.join(_PLUGIN, "config.json"),
]
_P = _PLUGIN
for _ in range(4):  # 从插件目录往上 4 层到 qqbot/
    _P = os.path.dirname(_P)
_CANDIDATE_CONFIGS.append(os.path.join(_P, "dafeiyu", "plugins", "fish-tail-config.json"))
_DEFAULT_CONFIG_PATH = _CANDIDATE_CONFIGS[-1]  # 兼容旧引用

# 允许环境变量覆盖（GitHub 通用安装时用）
_ENV_CONFIG = os.environ.get("FISH_TAIL_CONFIG")
if _ENV_CONFIG:
    _CANDIDATE_CONFIGS.insert(0, _ENV_CONFIG)


class PersonaConfig:
    """
    读取共享配置 + 人设文件，给注入指令提供「这条鱼自己的性格和口味」。

    原则：性格底色优先从人设文件（鲸鲸人设.md）提取，读不到才用配置兜底；
    投喂爱好完全按配置（鲸鲸爱零食/饭团/白饭，蛋糕是欠账），不再写死米饭。
    """
    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or _DEFAULT_CONFIG_PATH
        self.data: dict = {}
        self._load()
        self.persona_text = self._read_persona()

    def _load(self):
        if os.path.exists(self.config_path):
            candidates = [self.config_path] + [c for c in _CANDIDATE_CONFIGS if c != self.config_path]
        else:
            candidates = list(_CANDIDATE_CONFIGS)
        for p in candidates:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data:
                    self.data = data
                    self.config_path = p
                    return
            except Exception:
                continue
        self.data = {}

    def _read_persona(self) -> str:
        p = (self.data.get("性格", {}) or {}).get("来源文件", "")
        if not p or not os.path.exists(p):
            return ""
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    @property
    def persona_baseline(self) -> str:
        """从人设正文里抽最关键的身份句；抽不到用兜底。短而准，别塞整段。"""
        pick = []
        for ln in self.persona_text.splitlines():
            s = ln.strip().lstrip("-").strip()
            if not s or s.startswith(">"):
                continue
            # 只挑最能定义"这条鱼是谁"的短句
            if any(k in s for k in ("蓝色大肥鱼", "爱睡觉的大肥鱼", "住在老大", "养着的那只")):
                pick.append(s)
        if pick:
            return "；".join(dict.fromkeys(pick)).rstrip("。；")[:120]
        return (self.data.get("性格", {}) or {}).get("兜底底色", "一条爱睡觉的蓝色大肥鱼")

    @property
    def food_keywords(self) -> list[str]:
        return (self.data.get("投喂", {}) or {}).get(
            "食物关键词", ["米饭", "🍚", "零食", "蛋糕", "投喂", "吃"]
        )

    @property
    def food_hungry_seeds(self) -> list[str]:
        return (self.data.get("投喂", {}) or {}).get(
            "投喂后神态", ACTION_MAP["嘴馋"]
        )

    @property
    def food_full_seeds(self) -> list[str]:
        return (self.data.get("投喂", {}) or {}).get(
            "吃饱后神态", ACTION_MAP["吃饱"]
        )

    @property
    def forbid_fat(self) -> bool:
        return bool((self.data.get("性格", {}) or {}).get("禁止写胖", True))


@dataclass
class TailState:
    """判定出的鱼此刻状态。"""
    emotion: str
    trigger: str = ""
    context_hint: str = ""


class RuleEngine:
    """
    规则引擎：不靠大模型猜心情，用简单可靠的逻辑先判一遍。

    判定来源：
      - 用户消息关键词（"好累" -> 疲惫；"乖/摸摸头" -> 示好；"笨/傻" -> 嘴硬傲娇）
      - 当前时间（凌晨 -> 疲惫）
      - 用户习惯（传入 habit 字典，如 {"night_owl": True, "praise_loving": True}）
      - 投喂关键词从配置读（鲸鲸爱零食/饭团/白饭，蛋糕是欠账），不写死米饭
    """

    # 关键词 -> 情绪（顺序敏感：先匹配更具体的）
    KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
        (("好累", "累了", "困了", "疲惫", "加班", "熬夜了"), "疲惫"),
        (("摸摸头", "乖", "抱抱", "亲亲", "棒棒", "真棒", "夸"), "示好"),
        (("笨蛋", "傻", "大肥鱼", "蠢", "哼", "讨厌"), "嘴硬"),
        (("对不起", "抱歉", "别生气", "委屈", "冷落", "不理"), "委屈"),
        (("好吃", "投喂", "米饭", "🍚", "饭饭", "饿", "吃什么"), "嘴馋"),
        (("吃饱", "好饱", "吃饱了", "撑"), "吃饱"),
        (("厉害", "牛", "好棒", "太强", "崇拜"), "得瑟"),
        (("小心", "危险", "注意", "警惕"), "警惕"),
        (("生气", "气死", "恼", "火大"), "生气"),
        (("开心", "高兴", "哈哈", "嘿嘿", "好耶"), "开心"),
    ]

    def judge(
        self,
        user_text: str,
        now: datetime.datetime | None = None,
        habit: dict | None = None,
        config: "PersonaConfig | None" = None,
    ) -> TailState:
        now = now or datetime.datetime.now()
        habit = habit or {}
        text = (user_text or "").strip()
        low = text.lower()

        # 0) 投喂：用配置里「这条鱼自己的爱好」判断，不写死米饭
        if config and any(kw in low for kw in config.food_keywords):
            return TailState("嘴馋", trigger="投喂-按TA的爱好", context_hint=text[:40])

        # 1) 关键词
        for kws, emotion in self.KEYWORD_RULES:
            if any(kw in low for kw in kws):
                return TailState(emotion, trigger="关键词", context_hint=text[:40])

        # 2) 时间：深夜/凌晨 -> 疲惫（若习惯是夜猫子则更明显）
        hour = now.hour
        if hour >= 23 or hour < 5:
            hint = "夜猫子主人又来了" if habit.get("night_owl") else "这个点还醒着"
            return TailState("疲惫", trigger="深夜", context_hint=hint)

        # 3) 习惯：常被夸 -> 得瑟
        if habit.get("praise_loving") and any(k in low for k in ("夸", "棒", "喜欢你", "可爱")):
            return TailState("得瑟", trigger="习惯-爱被夸", context_hint="主人又夸了")

        # 4) 默认：慵懒底色（参考图里鱼的底色是聪明慵懒的小鲸鱼）
        return TailState("慵懒", trigger="默认底色", context_hint="")


class Injector:
    """
    动态注入器：把判定结果拼成一段 system 提示词。

    关键（参考图第四、五张）：
      · 给种子动作打样，但严禁完全照抄 —— 逼模型结合上下文用全新细节发散
      · 缓存最近 N 次生成的动作，注入「绝对不要使用以下最近出现过的动作」防重复
      · 明确格式：中文小括号（）里的动作/神态，缀在回复里
      · 禁止写「胖」
    """

    RECENT_N = 3

    def __init__(self, recent_store_path: str | None = None, recent_n: int = RECENT_N,
                 config: PersonaConfig | None = None):
        self.recent_store_path = recent_store_path
        self.recent_n = recent_n
        self.config = config or PersonaConfig()
        self._recent: list[str] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if not self.recent_store_path or not os.path.exists(self.recent_store_path):
            return
        try:
            with open(self.recent_store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._recent = [str(x) for x in data][-self.recent_n:]
        except Exception:
            self._recent = []

    def _save(self):
        if not self.recent_store_path:
            return
        try:
            os.makedirs(os.path.dirname(self.recent_store_path) or ".", exist_ok=True)
            with open(self.recent_store_path, "w", encoding="utf-8") as f:
                json.dump(self._recent[-self.recent_n:], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def remember_action(self, raw_reply: str) -> None:
        """从模型回复里抽出括号动作，记入最近缓存（供下一轮去重）。"""
        found = re.findall(r"（[^）]{2,40}）", raw_reply or "")
        if not found:
            return
        with self._lock:
            for a in found:
                if a not in self._recent:
                    self._recent.append(a)
            self._recent = self._recent[-self.recent_n:]
            self._save()

    def build(self, state: TailState) -> str:
        # 种子动作：嘴馋/吃饱按配置里「这条鱼自己的口味」，不写死米饭
        if state.emotion == "嘴馋":
            seeds = self.config.food_hungry_seeds
        elif state.emotion == "吃饱":
            seeds = self.config.food_full_seeds
        else:
            seeds = ACTION_MAP.get(state.emotion, ACTION_MAP["慵懒"])
        seed_text = "、".join(seeds[:4])
        fallback = EMOTION_FALLBACK.get(state.emotion, EMOTION_FALLBACK["慵懒"])
        baseline = self.config.persona_baseline
        full_words = "／".join(self.config.data.get("性格", {}).get("吃饱了只能写", ["圆滚滚", "毛茸茸"]))

        parts = [
            "[鱼的尾巴和插件·动态渲染]",
            "你的性格底色（沿用你自己，不是别人）：%s。" % baseline,
            "你现在的情绪底色是「%s」%s。" % (
                state.emotion,
                ("（%s）" % state.trigger) if state.trigger else "",
            ),
            "请参考基础动作包：%s。" % seed_text,
            "但**严禁完全照抄**这些种子词；请结合当前上下文和你自己的性格，用全新的细节描写你此刻"
            "尾巴、鳍和鳞片的动态（例如尾鳍的弧度、鳞片的光泽、水面的涟漪）。",
            "把动作写成中文小括号（）的形式，自然地缀在回复里，像内心戏一样，"
            "每条回复至少一处、篇幅简短（一句话以内），不要连成一长串。",
            "动作必须符合鱼的身体结构，只能用%s这类身体部位，不许出现人手、人脚。" % BODY_ANCHORS,
        ]
        if self.config.forbid_fat:
            parts.append("绝对不要写「胖」字；吃饱了只能写「%s」，不然会咬人。" % full_words)

        if state.context_hint:
            parts.insert(2, "上下文提示：%s。" % state.context_hint)

        with self._lock:
            recent = list(self._recent)
        if recent:
            parts.append("绝对不要使用以下最近出现过的动作：%s" % "；".join(recent))

        parts.append("示例（仅示意风格，别照搬）：%s" % fallback)
        parts.append("[/鱼的尾巴和插件]")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 便捷入口：一段文本 -> 注入指令
# ---------------------------------------------------------------------------
def build_injection(
    user_text: str,
    now: datetime.datetime | None = None,
    habit: dict | None = None,
    injector: Injector | None = None,
) -> tuple[str, TailState]:
    inj = injector or Injector()
    state = RuleEngine().judge(user_text, now=now, habit=habit, config=inj.config)
    return inj.build(state), state
