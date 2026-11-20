# dsh-fish-tail · 鱼的尾巴和插件（DSH 适配层）

根据上下文给鲸鲸的回复缀上小括号尾巴动作与神态。不改人设，只做「动作导演」。

## 安装

1. 把整个 `fish-tail-dsh` 目录拷到：
   `C:\Users\zyx\.dsh\profiles\desktop\node_modules\dsh-fish-tail`
2. 在 profile 的 `cordis.patch.yml` 加一行挂载（或让 DSH 设置页刷新插件列表）。
3. 重启 DSH。

## 原理

- `agent/pre-step` 读本步用户消息，用规则引擎判定鱼的心情（疲惫/示好/嘴硬/委屈/嘴馋…）。
- `systemPrompt.section({order:89991, interpolate:false})` 每步把动态指令注入 system prompt。
- `llm/stream` 抓每次回复文本，抽出括号动作记入最近缓存（最近 3 条）供去重。

核心逻辑与 AstrBot 版（`astrbot_plugin_fish_tail/core/engine.py`）保持同一套规则。
