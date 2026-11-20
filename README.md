# 鱼的尾巴和插件

根据上下文给机器人回复缀上**中文小括号（）的尾巴动作与神态**。不改人设，只做「动作导演」。

> 由鲸鲸（一只爱睡觉的蓝色大肥鱼）的铲屎官为其量身打造，现开源。
> 支持 **AstrBot**（QQ / PWA / webchat 共用后端）与 **DeepSeek Harness (DSH)** 两个平台。

## 效果示例

用户：「我今天好累啊」
> 好啦，先歇会儿。（尾鳍有气无力地扫过键盘，尾巴慢悠悠地拖在水里）

用户：「来块蛋糕🍰」
> 嘿嘿，这可是你说的。（尾巴期待地拍着水面，眼巴巴望着你手里的东西）

动作不是写死的，是模型按注入的指令结合上下文现场生成——每次都不一样。

## 它怎么工作（核心三件套）

1. **规则引擎**：读用户消息 + 时间，判定心情（疲惫 / 示好 / 嘴硬 / 委屈 / 嘴馋 / 开心 / 生气 / 慵懒……）。
2. **动作映射库**：每种心情 3-4 个种子动作词，只打样、不照抄。
3. **动态注入**：在 LLM 请求前塞一段 system 指令：
   - 「严禁完全照抄种子词，结合上下文用全新细节写尾巴/鳍/鳞片的动态」
   - **性格沿用角色自己**：从人设文件读身份句注入「你的性格底色」，不套外部硬编的性格
   - **投喂按角色爱好**：食物关键词和投喂神态都可配置，不写死米饭
   - 防重复：记住最近 3 次生成的动作，要求模型别再用
   - 防跑偏：只能用尾巴/尾鳍/鳞片，不许出现人手人脚

## 仓库结构

```
fish-tail-plugin/
├── config.json                       # 默认配置（通用，改这里换性格/口味）
├── astrbot/astrbot_plugin_fish_tail/ # AstrBot 插件完整包
└── dsh/dsh-fish-tail/                # DSH 插件完整包
```

## 安装

### AstrBot（QQ / PWA）

把 `astrbot/astrbot_plugin_fish_tail/` 整个目录拷进
`<AstrBot>/data/plugins/`，在 WebUI 插件页重载/启用，或重启 AstrBot。
PWA / webchat 共用同一后端，无需单独改。

### DeepSeek Harness (DSH)

把 `dsh/dsh-fish-tail/` 拷进
`<DSH profile>/node_modules/dsh-fish-tail`，再在 profile 的 `cordis.patch.yml` 加：

```yaml
- insert:
    - id: dsh-fish-tail
      name: 'dsh-fish-tail'
```

重启 DSH 生效。

## 配置

`config.json`（两个平台各有一份自带副本）：

- `性格.来源文件`：指向你的人设 md 路径，插件每次读它拿身份句；留空则用 `兜底底色`。
- `投喂.食物关键词` / `投喂后神态` / `吃饱后神态`：按你角色的爱好改。
- `禁止写胖`：默认 true（这条鱼被写胖会咬人）。
- AstrBot 版还支持环境变量 `FISH_TAIL_CONFIG` 指定配置路径。

## 测试

- AstrBot 核心引擎：`python tests/test_engine.py`（纯标准库）
- DSH 插件：`node test.mjs`（用模拟 ctx 验证判定/注入/去重）

## License

MIT
