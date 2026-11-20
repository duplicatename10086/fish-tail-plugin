// dsh-fish-tail —— 鱼的尾巴和插件（DSH 适配层）
// 根据上下文判定鱼的心情，动态注入 system 指令，让模型用中文小括号（）给回复
// 缀上尾巴/鳍/鳞片的动作神态。不改人设，只做「动作导演」。
//
// 机制（本机 dsh-fish-memory / dsh-obsidian-inbox 实战范式）：
//   - ctx.on('agent/pre-step', ...)        读本步用户消息 -> 判定情绪 -> 按会话缓存
//   - ctx.get('systemPrompt').section(...) 每步 text() 读缓存 -> 注入动态指令
//   - ctx.on('llm/stream', ...)            抓回复文本 -> 抽括号动作 -> 最近3条去重

export const name = 'dsh-fish-tail'
export const inject = []

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// 配置查找顺序：① 环境变量 FISH_TAIL_CONFIG（本机可指向真实人设配置）
//              ② 插件自带 config.json（仓库内，开箱即用）
const HERE = dirname(fileURLToPath(import.meta.url))
const BUNDLED_CONFIG = join(HERE, '..', 'config.json')
const ENV_CONFIG = process.env.FISH_TAIL_CONFIG || ''

function loadConfig() {
  let data = {}
  for (const p of [ENV_CONFIG, BUNDLED_CONFIG].filter(Boolean)) {
    try { data = JSON.parse(readFileSync(p, 'utf8')); if (data && Object.keys(data).length) break } catch { /* 试下一个 */ }
  }
  let personaText = ''
  try {
    const p = (data['性格'] || {})['来源文件']
    if (p) personaText = readFileSync(p, 'utf8')
  } catch { /* 用兜底 */ }
  // 从人设正文抽身份句
  let baseline = (data['性格'] || {})['兜底底色'] || '一条爱睡觉的蓝色大肥鱼'
  const picks = personaText.split(/\r?\n/).map((l) => l.trim().replace(/^-\s*/, ''))
    .filter((l) => l && !l.startsWith('>') && /蓝色大肥鱼|爱睡觉的大肥鱼|住在老大|养着的那只/.test(l))
  if (picks.length) baseline = Array.from(new Set(picks)).join('；').replace(/[。；]+$/, '').slice(0, 120)
  return {
    baseline,
    foodKeywords: (data['投喂'] || {})['食物关键词'] || ['米饭', '🍚', '零食', '蛋糕', '投喂', '吃'],
    hungrySeeds: (data['投喂'] || {})['投喂后神态'] || null,
    fullSeeds: (data['投喂'] || {})['吃饱后神态'] || null,
    forbidFat: (data['性格'] || {})['禁止写胖'] !== false,
    fullWords: ((data['性格'] || {})['吃饱了只能写'] || ['圆滚滚', '毛茸茸']).join('／'),
  }
}

// ---------------------------------------------------------------------------
// 规则引擎（与 AstrBot 版 core/engine.py 同一套规则）
// ---------------------------------------------------------------------------
const KEYWORD_RULES = [
  [['好累', '累了', '困了', '疲惫', '加班', '熬夜了'], '疲惫'],
  [['摸摸头', '乖', '抱抱', '亲亲', '棒棒', '真棒', '夸'], '示好'],
  [['笨蛋', '傻', '大肥鱼', '蠢', '哼', '讨厌'], '嘴硬'],
  [['对不起', '抱歉', '别生气', '委屈', '冷落', '不理'], '委屈'],
  [['好吃', '投喂', '米饭', '🍚', '饭饭', '饿', '吃什么'], '嘴馋'],
  [['吃饱', '好饱', '吃饱了', '撑'], '吃饱'],
  [['厉害', '牛', '好棒', '太强', '崇拜'], '得瑟'],
  [['小心', '危险', '注意', '警惕'], '警惕'],
  [['生气', '气死', '恼', '火大'], '生气'],
  [['开心', '高兴', '哈哈', '嘿嘿', '好耶'], '开心'],
]

const ACTION_MAP = {
  开心: ['尾尖勾起一个小弧度', '尾鳍欢快地拍打水面', '像螺旋桨一样转了个圈', '眼睛亮晶晶'],
  生气: ['尾鳍炸开', '啪啪狂拍水面', '僵硬地绷直', '鳞片微微竖起'],
  慵懒: ['尾巴软塌塌地垂着', '卷住自己', '有一下没一下地扫着地', '半眯着眼睛'],
  疲惫: ['半眯着眼睛打哈欠', '尾鳍有气无力地扫过键盘', '尾巴慢悠悠地拖在水里'],
  委屈: ['尾巴紧紧缠住手臂', '尾尖委屈地微微发抖', '背过身去只留个尾巴'],
  示好: ['尾巴轻轻蹭过来', '尾鳍卷住对方的手腕', '凑近了一点', '鳞片泛着柔光'],
  得瑟: ['尾巴翘得高高的', '连鳞片都在发光', '得意地晃了晃尾鳍'],
  警惕: ['尾巴绷直', '鳞片微张', '尾鳍警觉地摆了摆'],
  心疼: ['尾巴轻轻绕过来', '尾鳍蹭了蹭手背', '眼神软下来'],
  嘴硬: ['尾鳍别扭地甩到一边', '尾巴卷成小圈', '装作不在意地摆了摆'],
  嘴馋: ['尾巴期待地拍了拍水面', '鼻子动了动', '眼巴巴地望着那碗饭'],
  吃饱: ['尾巴满意地拍打着地面', '肚子圆滚滚的', '懒洋洋地晃了晃尾鳍'],
}
const FALLBACK = {
  开心: '（尾鳍欢快地拍了拍水面）', 生气: '（尾鳍炸开，啪啪拍着水面）',
  慵懒: '（尾巴软塌塌地垂着，半眯着眼睛）', 疲惫: '（半眯着眼打了个哈欠，尾鳍有气无力地扫过）',
  委屈: '（尾巴紧紧缠住手臂，尾尖微微发抖）', 示好: '（尾巴轻轻蹭了过来）',
  得瑟: '（尾巴翘得高高的，鳞片都在发光）', 警惕: '（尾巴绷直，鳞片微张）',
  心疼: '（尾巴轻轻绕过来，蹭了蹭手背）', 嘴硬: '（尾鳍别扭地甩到一边）',
  嘴馋: '（尾巴期待地拍了拍水面）', 吃饱: '（尾巴满意地拍打着地面）',
}

function judge(text = '', config = null) {
  const low = String(text || '')
  // 投喂：按配置里这条鱼自己的爱好，不写死米饭
  if (config && config.foodKeywords.some((k) => low.includes(k))) {
    return { emotion: '嘴馋', trigger: '投喂-按TA的爱好' }
  }
  for (const [kws, emo] of KEYWORD_RULES) {
    if (kws.some((k) => low.includes(k))) return { emotion: emo, trigger: '关键词' }
  }
  const h = new Date().getHours()
  if (h >= 23 || h < 5) return { emotion: '疲惫', trigger: '深夜' }
  return { emotion: '慵懒', trigger: '默认底色' }
}

function buildInstruction(state, recent, config) {
  let seedList
  if (state.emotion === '嘴馋') seedList = config?.hungrySeeds || ACTION_MAP['嘴馋']
  else if (state.emotion === '吃饱') seedList = config?.fullSeeds || ACTION_MAP['吃饱']
  else seedList = ACTION_MAP[state.emotion] || ACTION_MAP['慵懒']
  const seeds = seedList.slice(0, 4).join('、')
  const fb = FALLBACK[state.emotion] || FALLBACK['慵懒']
  const parts = [
    '[鱼的尾巴和插件·动态渲染]',
    `你的性格底色（沿用你自己，不是别人）：${config?.baseline || '一条爱睡觉的蓝色大肥鱼'}。`,
    `你现在的情绪底色是「${state.emotion}」${state.trigger ? '（' + state.trigger + '）' : ''}。`,
    `请参考基础动作包：${seeds}。`,
    '但**严禁完全照抄**这些种子词；请结合当前上下文和你自己的性格，用全新的细节描写你此刻尾巴、鳍和鳞片的动态（例如尾鳍的弧度、鳞片的光泽、水面的涟漪）。',
    '把动作写成中文小括号（）的形式，自然地缀在回复里，像内心戏一样，每条回复至少一处、篇幅简短（一句话以内），不要连成一长串。',
    '动作必须符合鱼的身体结构，只能用尾巴、尾鳍、鳞片这类身体部位，不许出现人手、人脚。',
  ]
  if (config?.forbidFat !== false) {
    parts.push(`绝对不要写「胖」字；吃饱了只能写「${config?.fullWords || '圆滚滚／毛茸茸'}」，不然会咬人。`)
  }
  if (recent && recent.length) {
    parts.push('绝对不要使用以下最近出现过的动作：' + recent.join('；'))
  }
  parts.push('示例（仅示意风格，别照搬）：' + fb)
  parts.push('[/鱼的尾巴和插件]')
  return parts.join('\n')
}

// 从消息里找最后一条用户文本
function lastUserText(messages) {
  if (!Array.isArray(messages)) return ''
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i] || {}
    const role = m.role || m.author?.role || ''
    if (role !== 'user' && role !== 'human') continue
    let c = m.content
    if (Array.isArray(c)) {
      c = c.map((p) => (typeof p === 'string' ? p : p?.text || '')).join('')
    }
    if (typeof c === 'string' && c.trim()) return c.trim()
  }
  return ''
}

// 从回复文本抽括号动作
function extractActions(text) {
  const found = String(text || '').match(/（[^）]{2,40}）/g) || []
  return found
}

// ---------------------------------------------------------------------------
// 插件主体
// ---------------------------------------------------------------------------
export function apply(ctx) {
  const config = loadConfig() // 性格从人设读、投喂按TA的爱好
  const emotionBySession = new Map() // sessionId -> {emotion, trigger}
  const recentBySession = new Map()  // sessionId -> string[]（最近3条动作）
  let sectionOff = null

  function sidOf(agent) {
    try { return String(agent?.session?.id || agent?.id || 'default') } catch { return 'default' }
  }

  // 1) 本步用户消息 -> 判定情绪，缓存
  ctx.on('agent/pre-step', async (payload, next) => {
    try {
      const agent = payload?.agent
      const sid = sidOf(agent)
      const text = lastUserText(payload?.messages)
      if (text) emotionBySession.set(sid, judge(text, config))
    } catch { /* 绝不影响主流程 */ }
    return next()
  })

  // 2) 每步组装 system prompt 时，读缓存情绪 -> 注入动态指令
  ctx.inject(['systemPrompt'], (sp) => {
    sectionOff = sp.section({
      name: 'fish-tail:dynamic',
      order: 89991, // 放最后，保护前面 prompt 缓存（参考 dsh-fish-memory）
      interpolate: false, // 指令里可能有 {{ }}，不让宿主当模板解析
      text: (context) => {
        // 从 assemble 上下文拿当前 agent，定位会话
        const sid = sidOf(context?.agent)
        let state = emotionBySession.get(sid)
        if (!state && emotionBySession.size) {
          state = Array.from(emotionBySession.values()).slice(-1)[0]
        }
        if (!state) return ''
        let recent = recentBySession.get(sid)
        if (!recent || !recent.length) {
          // 会话 key 格式可能不一致，退而取最近一次写入的
          const vals = Array.from(recentBySession.values()).filter((v) => v && v.length)
          recent = vals.length ? vals[vals.length - 1] : []
        }
        return buildInstruction(state, recent, config)
      },
    })
  })

  // 3) 抓每次回复文本，抽括号动作记入最近缓存（去重用）
  ctx.on('llm/stream', async (options, next) => {
    const sid = options?.sessionId ? String(options.sessionId) : 'default'
    const stream = await next()
    // 包装 async iterable，边转发边收集文本
    const self = this
    async function* collect() {
      let buf = ''
      try {
        for await (const chunk of stream) {
          try {
            const t = chunk?.type === 'text' || chunk?.type === 'delta'
              ? (chunk.text || chunk.delta || '')
              : (typeof chunk?.text === 'string' ? chunk.text : '')
            if (t) buf += t
          } catch { /* ignore */ }
          yield chunk
        }
      } finally {
        try {
          const acts = extractActions(buf)
          if (acts.length) {
            const cur = recentBySession.get(sid) || []
            for (const a of acts) if (!cur.includes(a)) cur.push(a)
            recentBySession.set(sid, cur.slice(-3))
          }
        } catch { /* ignore */ }
      }
    }
    return collect()
  })

  ctx.logger?.info?.('[fish-tail] 鱼的尾巴和插件已加载（pre-step 判定 + systemPrompt 注入 + 去重）')

  // 卸载清理：section 返回的是 Cordis effect disposer（函数，直接调）
  ctx.effect(() => () => {
    try { if (typeof sectionOff === 'function') sectionOff() } catch { /* ignore */ }
  }, 'fish-tail.dispose')
}
