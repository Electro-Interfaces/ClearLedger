/**
 * Прогон eco-rail.js без браузера: `node scripts/eco-rail-smoke.mjs`
 *
 * ЗАЧЕМ. Рельс это статика, её никто не собирает и не типизирует: опечатка или
 * потерянная при правке функция доезжают до стенда живыми. Так уже вышло 06.08.2026 -
 * из файла пропала workareaBox, render падал на ReferenceError, и блок пространства
 * в левом меню Поддержки исчезал целиком. Синтаксис при этом был безупречен.
 *
 * Проверка исполняет render на крошечном стабе DOM: открывает панель приложений и
 * смотрит, что разметка собралась и содержит группы стола.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import vm from 'node:vm'

const file = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'eco-rail.js')

const APPS = [
  { code: 'pulse', name: 'Пульс', icon: 'activity', layer: 'app', mode: 'internal', route: '/pulse', description: 'как идут дела' },
  { code: 'support', name: 'Поддержка', icon: 'life-buoy', layer: 'service', mode: 'sso', description: 'обращения и выезды' },
  { code: 'ops', name: 'Эксплуатация', icon: 'hard-hat', layer: 'app', mode: 'internal', route: '/ops' },
  { code: 'chat', name: 'Чаты', icon: 'messages-square', layer: 'service', mode: 'internal', route: '/chat' },
  { code: 'admin', name: 'Управление', icon: 'shield-check', layer: 'admin', mode: 'internal', route: '/admin' },
]

const listeners = []
const shadow = {
  innerHTML: '',
  getElementById: () => ({ onclick: null }),
  querySelector: () => null,
  querySelectorAll: () => [],
}
class HTMLElement {
  attachShadow() { return shadow }
  hasAttribute() { return false }
  getAttribute() { return null }
  get shadowRoot() { return this._sr }
  set shadowRoot(v) { this._sr = v }
  get style() { return this._style ||= {} }
}
const elements = new Map()
const sandbox = {
  HTMLElement,
  customElements: {
    define: (name, cls) => elements.set(name, cls),
    get: (name) => elements.get(name),
  },
  document: {
    addEventListener: () => {},
    removeEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: () => [],
    documentElement: {},
    body: {},
  },
  window: {
    addEventListener: (t, f) => listeners.push([t, f]),
    removeEventListener: () => {},
    getComputedStyle: () => ({ backgroundColor: 'rgb(15,17,21)', color: 'rgb(240,240,240)' }),
    location: { origin: 'https://rushydro.dataworker.ru', pathname: '/support/' },
  },
  localStorage: { getItem: () => 'токен-заглушка', setItem: () => {} },
  // Рельс ходит к Ядру абсолютным адресом (шим fetch приложения уводит относительные
  // пути в свою базу), поэтому в песочнице нужны и location, и URL
  location: { origin: 'https://rushydro.dataworker.ru', href: 'https://rushydro.dataworker.ru/support/', pathname: '/support/' },
  URL,
  URLSearchParams,
  fetch: async () => ({ ok: true, json: async () => ({ enabled: true, apps: APPS, profile_id: 'energy' }) }),
  console,
  setTimeout,
}
sandbox.globalThis = sandbox
sandbox.self = sandbox
sandbox.getComputedStyle = sandbox.window.getComputedStyle

vm.createContext(sandbox)
vm.runInContext(readFileSync(file, 'utf8'), sandbox, { filename: 'eco-rail.js' })

const EcoNav = elements.get('eco-nav')
if (!EcoNav) throw new Error('eco-nav не зарегистрирован')

const nav = new EcoNav()
nav.shadowRoot = shadow
nav.connectedCallback()
// Каталог грузится обещанием: без паузы панель проверялась бы пустой
await new Promise((r) => setTimeout(r, 0))
// Панель открывается тем же путём, что и по клику: приватное поле недоступно снаружи,
// поэтому дёргаем обработчик кнопки через подменённый getElementById
let onclick = null
shadow.getElementById = () => ({ set onclick(f) { onclick = f }, get onclick() { return onclick } })
nav.render()
if (!onclick) throw new Error('кнопка «Приложения» не получила обработчик')
onclick()

const html = shadow.innerHTML
// Строки — те же, что на столе Ядра (`src/config/spaceLauncher.ts`): проверка ловит
// расхождение панели в приложении со столом пространства.
const must = ['Приложения пространства', 'Управление', 'Клиенты и продажи',
  'Системные', 'Чаты']
for (const m of must) {
  if (!html.includes(m)) throw new Error(`в разметке панели нет «${m}»`)
}
if (!html.includes('position:fixed')) throw new Error('панель без позиционирования')
// Плитка обязана нести иконку продукта и точку готовности - без них панель
// вырождается в список одинаковых карточек, что и было до 06.08.2026
if (!html.includes('class="ico"')) throw new Error('плитки без иконок продуктов')
if (!html.includes('class="dot"')) throw new Error('плитки без точки готовности')

// Карта готовности продублирована из spaceProducts.ts - сверяем, что не разъехалась
const rail = readFileSync(file, 'utf8')
const cfg = readFileSync(path.join(path.dirname(file), '..', 'src', 'config', 'spaceProducts.ts'), 'utf8')
const mapOf = (src, marker) => {
  const i = src.indexOf(marker)
  const body = src.slice(src.indexOf('{', i) + 1, src.indexOf('}', src.indexOf('{', i)))
  return Object.fromEntries([...body.matchAll(/(\w+):\s*'(\w+)'/g)].map((m) => [m[1], m[2]]))
}
const inRail = mapOf(rail, 'const READINESS = ')
const inCfg = mapOf(cfg, 'PRODUCT_READINESS: Record<string, Readiness> = ')
for (const [code, state] of Object.entries(inCfg)) {
  if (inRail[code] !== state) {
    throw new Error(`готовность «${code}» разъехалась: в spaceProducts.ts ${state}, в рельсе ${inRail[code]}`)
  }
}
for (const code of Object.keys(inRail)) {
  if (!(code in inCfg)) throw new Error(`в рельсе лишний продукт «${code}»`)
}
console.log('eco-rail: render и панель отработали, разметка собрана')
