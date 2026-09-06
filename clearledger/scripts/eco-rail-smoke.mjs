/**
 * Прогон eco-rail.js без браузера: `node scripts/eco-rail-smoke.mjs`
 *
 * ЗАЧЕМ. Рельс это статика, её никто не собирает и не типизирует: опечатка или
 * потерянная при правке функция доезжают до стенда живыми. Так уже вышло 06.08.2026 -
 * из файла пропала workareaBox, render падал на ReferenceError, и блок пространства
 * в левом меню Поддержки исчезал целиком. Синтаксис при этом был безупречен.
 *
 * Проверка исполняет render на крошечном стабе DOM: открывает панель приложений и
 * смотрит, что разметка собралась. Плиток в ней больше нет — витрину показывает
 * фреймом стол Ядра (`/apps`), поэтому проверяем именно фрейм и его адрес.
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
if (!html.includes('Приложения пространства')) throw new Error('панель без заголовка')
if (!html.includes('position:fixed')) throw new Error('панель без позиционирования')
// Витрина — фрейм со столом Ядра во встроенном виде. Своей разметки плиток у панели
// нет с 06.09.2026: каталог, слои, избранное и вид одни на всё пространство.
if (!/<iframe[^>]+class="apps"/.test(html)) throw new Error('панель без фрейма витрины')
if (!/src="[^"]*\/apps\?theme=(dark|light)"/.test(html)) {
  throw new Error('фрейм витрины без адреса стола или без темы хозяина')
}
// Тема берётся у приложения-хозяина: стаб отдаёт тёмный фон страницы.
if (!html.includes('theme=dark')) throw new Error('тёмное приложение получило светлую витрину')
// Блок Ядра в меню остаётся: страницы пространства открываются под рабочим местом.
if (!html.includes('/ops/intake')) throw new Error('в меню нет страниц Ядра')

console.log('eco-rail: render, меню Ядра и фрейм витрины отработали')
