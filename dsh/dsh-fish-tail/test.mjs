// 模拟 Cordis ctx，验证 dsh-fish-tail 的核心逻辑（不加载进真实 DSH）
const handlers = { 'agent/pre-step': [], 'llm/stream': [] }
let sectionOpts = null
let sectionOffCalled = false

const ctx = {
  logger: { info() {}, warn() {} },
  on(event, fn) { if (handlers[event]) handlers[event].push(fn) },
  inject(names, fn) {
    if (names.includes('systemPrompt')) {
      fn({
        section(opts) {
          sectionOpts = opts
          return () => { sectionOffCalled = true }
        },
      })
    }
  },
  effect(fn, label) { fn() },
}

const mod = await import('./lib/index.js')
mod.apply(ctx)

// 1) 模拟 pre-step：用户说"我今天好累啊"
const agent = { id: 'a1', session: { id: 's1' } }
const messages = [{ role: 'user', content: '我今天好累啊' }]
let nextCalled = false
for (const h of handlers['agent/pre-step']) {
  await h({ agent, messages }, async () => { nextCalled = true })
}
console.log('pre-step next 调用:', nextCalled)

// 2) 触发 section 的 text()
const text = sectionOpts.text({ agent })
console.log('--- 注入文本 ---')
console.log(text)

if (!text.includes('疲惫')) throw new Error('未判定出疲惫情绪')
if (!text.includes('严禁完全照抄')) throw new Error('缺少发散指令')
if (!text.includes('绝对不要写「胖」字')) throw new Error('缺少防胖规则')
if (!text.includes('蓝色大肥鱼')) throw new Error('性格底色未从人设读取')
if (sectionOpts.interpolate !== false) throw new Error('interpolate 应为 false')

// 1b) 投喂用例：蛋糕应按配置里的爱好判嘴馋、用配置投喂神态
for (const h of handlers['agent/pre-step']) {
  await h({ agent, messages: [{ role: 'user', content: '来吃块蛋糕' }] }, async () => {})
}
const text2 = sectionOpts.text({ agent })
console.log('--- 投喂注入（判定+口味） ---')
console.log(text2.split('\n').filter((l) => /情绪底色|基础动作包|性格底色/.test(l)).join('\n'))
if (!text2.includes('嘴馋')) throw new Error('投喂未判嘴馋')
if (!text2.includes('眼巴巴望着你手里的东西')) throw new Error('投喂神态未从配置读取')

// 3) 模拟 llm/stream 收集动作做去重
async function* fakeStream() {
  yield { type: 'text', text: '好啦（尾巴软塌塌地垂着，半眯着眼）' }
}
const wrapped = await handlers['llm/stream'][0].call(ctx, { sessionId: 's1' }, async () => fakeStream())
let collected = ''
for await (const c of wrapped) collected += c.text || ''
console.log('stream 转发文本:', collected)
if (!collected.includes('尾巴软塌塌')) throw new Error('stream 转发失败')

const text3 = sectionOpts.text({ agent })
console.log('--- 去重后的注入含最近动作 ---')
console.log(text3.split('\n').filter((l) => l.includes('最近出现过')).join('\n') || '(无最近动作行)')

console.log('\n全部 DSH 插件逻辑测试通过')
