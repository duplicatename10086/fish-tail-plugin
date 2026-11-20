# -*- coding: utf-8 -*-
r"""
鱼的尾巴和插件 —— AstrBot 适配层

把跨平台核心引擎（core/engine.py）挂到 AstrBot 的 on_llm_request 钩子上：
每次 LLM 请求前，判定鱼此刻的心情，往 system_prompt 注入一段动态指令，
让模型用中文小括号（）给回复缀上尾巴/鳍/鳞片的动作与神态。

不改人设、不生成尾巴文字本身，只做「动作导演」。
PWA / webchat 与 QQ 共用同一后端，此处注入即全平台生效。
"""
from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.star.star_tools import StarTools

from .core.engine import Injector, RuleEngine

# 注入段落的 HTML 注释标记（借鉴 meme_manager 的成熟范式，防重复累积）
MARK_START = "<!-- fish-tail:start -->"
MARK_END = "<!-- fish-tail:end -->"


@register(
    "astrbot_plugin_fish_tail",
    "鲸鲸的小惊云",
    "根据上下文给鲸鲸的回复缀上小括号尾巴动作与神态（跨平台核心引擎）",
    "1.0.0",
    "https://github.com/local/fish-tail",
)
class FishTailPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._enabled = bool(self.config.get("enabled", True))
        self._engine = RuleEngine()
        data_dir = StarTools.get_data_dir("astrbot_plugin_fish_tail")
        self._injector = Injector(recent_store_path=data_dir / "recent_actions.json")

    def _strip_fragment(self, prompt: str) -> str:
        """剥掉之前注入的旧片段，防止累积（只要标记之间的内容）。"""
        if not prompt or MARK_START not in prompt:
            return prompt or ""
        before = prompt.split(MARK_START, 1)[0]
        rest = prompt.split(MARK_END, 1)
        after = rest[1] if len(rest) == 2 else ""
        return (before + after).strip()

    @filter.on_llm_request(priority=60000)
    async def fish_tail_inject(self, event: AstrMessageEvent, req: ProviderRequest):
        if not self._enabled:
            return
        try:
            # 用户消息优先用 req.prompt（已是纯文本），回退事件文本
            user_text = (getattr(req, "prompt", None) or "").strip()
            if not user_text:
                getter = getattr(event, "get_message_str", None)
                user_text = (getter() if callable(getter) else "").strip()
            if not user_text:
                return
            # 跳过工具中间消息/AstrBot 内部占位
            if "Tool intermediate" in user_text or user_text.startswith("[系统"):
                return

            state = self._engine.judge(user_text, config=self._injector.config)
            fragment = MARK_START + "\n" + self._injector.build(state) + "\n" + MARK_END
            current = self._strip_fragment(str(getattr(req, "system_prompt", "") or ""))
            req.system_prompt = (current + "\n\n" + fragment).strip()
            logger.debug("[鱼的尾巴] 注入情绪=%s 触发=%s" % (state.emotion, state.trigger))
        except Exception as e:
            logger.warning("[鱼的尾巴] 注入失败（已跳过）: %s" % e)

    @filter.on_llm_response(priority=60000)
    async def fish_tail_remember(self, event: AstrMessageEvent, response: LLMResponse):
        """从模型回复里抽出括号动作，记入最近缓存供下一轮去重。"""
        if not self._enabled:
            return
        try:
            text = ""
            raw = getattr(response, "raw_completion", None)
            if isinstance(raw, str) and raw.strip():
                text = raw
            if not text:
                chain = getattr(response, "result_chain", None)
                if chain is not None:
                    parts = chain if isinstance(chain, (list, tuple)) else [chain]
                    text = " ".join(
                        str(getattr(c, "text", "") or getattr(c, "content", "") or "")
                        for c in parts
                    )
            if text:
                self._injector.remember_action(text)
        except Exception as e:
            logger.debug("[鱼的尾巴] 记忆动作失败（已跳过）: %s" % e)

    async def terminate(self):
        self._enabled = False
