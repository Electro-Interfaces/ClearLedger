/**
 * <eco-rail> — экосистемная панель контейнера для приложений ВНЕ Ledger.
 *
 * Ядро отдаёт этот файл по адресу `/eco/rail.js` (nginx стека), приложение подключает
 * одной строкой и получает выход на рабочий стол, переход в соседний продукт и в
 * «Управление». Реализация одна на все приложения — ванильный web-component, без React
 * и без сборки, поэтому годится и для чужих фронтов.
 *
 * Раньше это была вертикальная колонка у правого края. Колонку убрали: она съедала
 * ширину у каждого приложения и дублировала переходы, которые есть в шапке. Теперь —
 * компактная плашка в правом верхнем углу, поверх контента и без отступов у страницы.
 *
 *   <script defer src="/eco/rail.js"></script>
 *   <eco-rail admin></eco-rail>          // admin — показать «Центр управления»
 *
 * Атрибуты (все необязательные):
 *   home       — адрес рабочего стола (по умолчанию «/»)
 *   admin-url  — адрес Центра управления (по умолчанию «/admin»)
 *   admin      — присутствует → показывать переход в Центр управления
 *   label      — подпись экосистемы во всплывающей подсказке
 *
 * Признак `admin` приложение берёт из handoff-токена Ядра (клейм `adm`). Это ТОЛЬКО
 * про отрисовку кнопки: права проверяет Ядро — не-админа оно вернёт на стол.
 *
 * ПЕРЕКЛЮЧАТЕЛЬ ПРОДУКТОВ. Каталог берётся из единого реестра Ядра
 * (`GET /api/sso/apps`) — того же, что питает рабочий стол и рельс Ledger, поэтому
 * отключённый в «Управлении» продукт исчезает и здесь. Приложения контейнера живут
 * на ОДНОМ origin (docs/CORE.md §6), значит токен Ядра лежит в том же localStorage —
 * им и авторизуемся. Токена нет (человек вошёл прямой формой приложения, минуя Ядро)
 * или каталог не ответил — кнопки просто не будет: рельс не должен ломать приложение.
 *
 * Плашка висит поверх страницы и ширины у неё не отнимает — отступов приложению
 * добавлять не нужно.
 */
;(() => {
  if (customElements.get('eco-rail')) return

  const RAIL_W = 48
  const STYLE_ID = 'eco-rail-page-offset'
  // Ключ токена Ядра в localStorage — тот же, что у фронта Ledger (services/apiClient.ts).
  // Один origin на контейнер делает хранилище общим, поэтому приложению достаточно того,
  // что человек уже вошёл в Ядро.
  const TOKEN_KEY = 'clearledger-token'

  // Иконки — контуры lucide (тот же язык, что в Ledger), currentColor.
  const ICONS = {
    home: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    apps: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="M2 9h20"/><path d="M6 4v5"/>',
    external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h6"/>',
  }

  const token = () => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  }

  /** Запрос к Ядру от имени уже вошедшего человека. Ошибку отдаём наверх — рельс её глотает. */
  async function core(path) {
    const t = token()
    if (!t) throw new Error('no token')
    const r = await fetch(path, { headers: { Authorization: `Bearer ${t}` } })
    if (!r.ok) throw new Error(String(r.status))
    return r.json()
  }

  const sameOrigin = (url) => {
    try { return new URL(url, location.href).origin === location.origin } catch { return false }
  }

  /** Пользователь просит новую вкладку — как в любой ссылке (Ctrl/⌘/Shift, средняя кнопка). */
  const wantsNewTab = (e) => !!e && (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1)

  // Имя продукта приходит из реестра, где его вводит админ, а рисуем мы через innerHTML.
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ))

  const svg = (paths) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`

  // Плавающая плашка ширины у страницы не отнимает: отступ снимаем, если остался
  // от прежней версии рельса (человек мог не перезагрузить вкладку).
  function ensurePageOffset() {
    document.getElementById(STYLE_ID)?.remove()
  }

  function dropPageOffset() {
    document.getElementById(STYLE_ID)?.remove()
  }

  class EcoRail extends HTMLElement {
    static observedAttributes = ['admin', 'home', 'admin-url', 'label']

    // Каталог продуктов: null — ещё не спрашивали, [] — спросили и пусто (или не ответил).
    #apps = null
    #open = false
    #busy = null

    connectedCallback() {
      ensurePageOffset()
      this.render()
      // Закрытие списка — как у любого поповера: клик мимо и Esc.
      this.onDocClick = (e) => { if (this.#open && !e.composedPath().includes(this)) this.#close() }
      this.onKey = (e) => { if (e.key === 'Escape') this.#close() }
      document.addEventListener('click', this.onDocClick)
      document.addEventListener('keydown', this.onKey)
    }

    disconnectedCallback() {
      document.removeEventListener('click', this.onDocClick)
      document.removeEventListener('keydown', this.onKey)
      if (!document.querySelector('eco-rail')) dropPageOffset()
    }

    #close() {
      if (!this.#open) return
      this.#open = false
      this.render()
    }

    /** Открыть список: каталог спрашиваем один раз, при первом обращении. */
    async #toggle() {
      if (this.#open) return this.#close()
      this.#open = true
      this.render()
      if (this.#apps !== null) return
      try {
        const data = await core('/api/sso/apps')
        // Компанию не передаём: Ядро возьмёт выбранную человеком (X-Company-Id или его
        // компанию по умолчанию) — тот же список, что на рабочем столе.
        this.#apps = data && data.enabled ? (data.apps || []) : []
      } catch {
        this.#apps = []   // не вошли в Ядро или каталог недоступен — честно покажем это
      }
      if (this.#open) this.render()
    }

    /**
     * Открытие продукта — та же механика, что у лаунчера Ядра (hooks/useOpenApp.ts):
     * internal живёт в SPA Ядра (адрес от корня), остальным Ядро выпускает адрес перехода
     * (для sso — с handoff-токеном, для моста — просто адрес).
     */
    async #openApp(app, newTab) {
      if (this.#busy) return
      if (app.mode === 'internal' && app.route) {
        if (newTab) window.open(app.route, '_blank', 'noopener,noreferrer')
        else location.assign(app.route)
        return
      }
      this.#busy = app.code
      this.render()
      try {
        const r = await core(`/api/sso/authorize?app=${encodeURIComponent(app.code)}`)
        // Чужой домен (мост) — всегда новой вкладкой: там своя сессия и свой «назад».
        if (newTab || !sameOrigin(r.url)) window.open(r.url, '_blank', 'noopener,noreferrer')
        else location.assign(r.url)
      } catch {
        /* молча: рельс — вспомогательная навигация, ронять из-за него приложение нельзя */
      } finally {
        this.#busy = null
        this.render()
      }
    }

    attributeChangedCallback() {
      if (this.shadowRoot) this.render()
    }

    /** Программная установка признака админа: rail.admin = true */
    set admin(v) {
      if (v) this.setAttribute('admin', '')
      else this.removeAttribute('admin')
    }

    get admin() {
      return this.hasAttribute('admin')
    }

    render() {
      const root = this.shadowRoot ?? this.attachShadow({ mode: 'open' })
      const home = this.getAttribute('home') || '/'
      const adminUrl = this.getAttribute('admin-url') || '/admin'
      const label = this.getAttribute('label') || 'Экосистема'
      const showAdmin = this.hasAttribute('admin')
      // Без токена Ядра переключатель показывать нечем: человек вошёл прямой формой
      // приложения. Дорога в пространство у него остаётся через «Стол».
      const showApps = !!token()

      // Цвета намеренно нейтральные (полупрозрачный серый + currentColor): рельс
      // одинаково читается на светлой и тёмной теме любого приложения, не требуя
      // от него ни переменных, ни классов.
      root.innerHTML = `
        <style>
          :host{
            position:fixed; top:10px; right:12px; z-index:2147483000;
            display:flex; flex-direction:row; align-items:center;
            gap:2px; padding:3px; box-sizing:border-box;
            border:1px solid rgba(127,127,127,.28); border-radius:10px;
            background:rgba(127,127,127,.10); backdrop-filter:blur(6px);
            box-shadow:0 2px 10px rgba(0,0,0,.10);
            font:500 12px/1.2 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
          }
          a,button{
            display:flex; flex-direction:row; align-items:center; gap:5px;
            padding:5px 9px; border:0; border-radius:8px; text-decoration:none; white-space:nowrap;
            background:none; color:inherit; font:inherit; cursor:pointer;
            opacity:.72; transition:background .15s,opacity .15s;
          }
          a:hover,button:hover{ background:rgba(127,127,127,.18); opacity:1 }
          button[aria-expanded="true"]{ background:rgba(127,127,127,.18); opacity:1 }
          svg{ width:16px; height:16px; flex:none }
          span{ text-align:left }
          /* Список продуктов. Фон размывает подложку, текст — currentColor приложения:
             так панель читается и на светлой, и на тёмной теме, не зная о них. */
          .apps{
            position:absolute; right:0; top:calc(100% + 6px); width:224px;
            max-height:min(70vh,420px); overflow:auto; padding:4px; box-sizing:border-box;
            border:1px solid rgba(127,127,127,.28); border-radius:12px;
            background:rgba(127,127,127,.14); backdrop-filter:blur(16px) saturate(160%);
            box-shadow:0 8px 28px rgba(0,0,0,.28); font-size:13px;
          }
          .apps .head{ padding:6px 8px 4px; font-size:11px; opacity:.6 }
          .apps button{
            flex-direction:row; align-items:center; justify-content:flex-start; gap:8px;
            width:100%; padding:7px 8px; text-align:left; opacity:.9; border-radius:8px;
          }
          .apps .empty{ padding:8px; opacity:.6; font-size:12px }
          .spin{ animation:eco-spin 1s linear infinite }
          @keyframes eco-spin{ to{ transform:rotate(360deg) } }
        </style>
        <a href="${home}" title="Рабочий стол · ${label}">${svg(ICONS.home)}<span>Стол</span></a>
        ${showApps ? `
          <button id="apps-btn" aria-expanded="${this.#open}" title="Продукты пространства">
            ${svg(ICONS.apps)}<span>Прилож.</span>
          </button>` : ''}
        ${showAdmin
          ? `<a href="${adminUrl}" title="Центр управления">${svg(ICONS.shield)}<span>Центр</span></a>`
          : ''}
        ${this.#open ? this.#appsHtml(label) : ''}
      `

      root.getElementById('apps-btn')?.addEventListener('click', () => this.#toggle())
      root.querySelectorAll('[data-app]').forEach((el) => {
        const app = (this.#apps || []).find((a) => a.code === el.dataset.app)
        if (!app) return
        el.addEventListener('click', (e) => this.#openApp(app, wantsNewTab(e)))
        el.addEventListener('auxclick', (e) => { if (e.button === 1) this.#openApp(app, true) })
      })
    }

    #appsHtml(label) {
      if (this.#apps === null) return `<div class="apps"><div class="empty">Загрузка…</div></div>`
      if (!this.#apps.length) {
        return `<div class="apps"><div class="empty">Продукты недоступны — войдите в пространство на рабочем столе.</div></div>`
      }
      return `
        <div class="apps">
          <div class="head">${label}</div>
          ${this.#apps.map((a) => `
            <button data-app="${escapeHtml(a.code)}">
              ${this.#busy === a.code
                ? `<span class="spin">${svg(ICONS.apps)}</span>`
                : svg(a.mode === 'link' ? ICONS.external : ICONS.apps)}
              <span>${escapeHtml(a.name || a.code)}</span>
            </button>`).join('')}
        </div>`
    }
  }

  customElements.define('eco-rail', EcoRail)

  /**
   * <eco-apps> — «Стол» и «Приложения» в ШАПКЕ приложения контейнера.
   *
   * Тот же жест, что в Ядре (`DeskButton` + `AppLauncher`): сначала вернуться на стол,
   * потом выбрать, куда идти дальше. Рельс остаётся для навигации по краю экрана, но
   * переход между продуктами нужен так же часто, как прикладные кнопки рядом, — поэтому
   * он живёт в шапке, а не прячется в углу.
   *
   *   <eco-apps></eco-apps>            // внутри своей шапки, рядом с кнопками приложения
   *
   * Атрибуты: `home` (адрес стола, по умолчанию «/»), `label` (подпись списка).
   * Каталог и открытие — общие с рельсом (см. выше), поэтому отключённый в «Управлении»
   * продукт исчезает и здесь. Без токена Ядра компонент не рисует ничего.
   */
  class EcoApps extends HTMLElement {
    #apps = null
    #open = false
    #busy = null

    connectedCallback() {
      this.render()
      this.onDocClick = (e) => { if (this.#open && !e.composedPath().includes(this)) this.#close() }
      this.onKey = (e) => { if (e.key === 'Escape') this.#close() }
      document.addEventListener('click', this.onDocClick)
      document.addEventListener('keydown', this.onKey)
    }

    disconnectedCallback() {
      document.removeEventListener('click', this.onDocClick)
      document.removeEventListener('keydown', this.onKey)
    }

    #close() { if (this.#open) { this.#open = false; this.render() } }

    async #toggle() {
      if (this.#open) return this.#close()
      this.#open = true
      this.render()
      if (this.#apps !== null) return
      try {
        const data = await core('/api/sso/apps')
        this.#apps = data && data.enabled ? (data.apps || []) : []
      } catch {
        this.#apps = []
      }
      if (this.#open) this.render()
    }

    async #openApp(app, newTab) {
      if (this.#busy) return
      if (app.mode === 'internal' && app.route) {
        if (newTab) window.open(app.route, '_blank', 'noopener,noreferrer')
        else location.assign(app.route)
        return
      }
      this.#busy = app.code
      this.render()
      try {
        const r = await core(`/api/sso/authorize?app=${encodeURIComponent(app.code)}`)
        if (newTab || !sameOrigin(r.url)) window.open(r.url, '_blank', 'noopener,noreferrer')
        else location.assign(r.url)
      } catch {
        /* переход между продуктами не должен ронять приложение */
      } finally {
        this.#busy = null
        this.render()
      }
    }

    render() {
      const root = this.shadowRoot ?? this.attachShadow({ mode: 'open' })
      const home = this.getAttribute('home') || '/'
      const label = this.getAttribute('label') || 'Пространство'
      // Нет токена Ядра — человек вошёл прямой формой приложения: показывать ему
      // переключатель продуктов не на что.
      if (!token()) { root.innerHTML = ''; return }

      root.innerHTML = `
        <style>
          :host{ display:inline-flex; align-items:center; gap:8px; position:relative;
                 font:inherit; color:inherit }
          button{
            display:inline-flex; align-items:center; gap:8px; height:44px; padding:0 12px;
            border-radius:12px; border:1px solid currentColor; background:none; color:inherit;
            font:inherit; font-weight:500; font-size:14px; cursor:pointer; opacity:.85;
            transition:opacity .15s, background .15s;
          }
          button:hover{ opacity:1; background:rgba(127,127,127,.14) }
          svg{ width:16px; height:16px; flex:none }
          .menu{
            position:absolute; top:52px; left:0; z-index:2147483000; width:232px; padding:4px;
            box-sizing:border-box; border:1px solid rgba(127,127,127,.28); border-radius:12px;
            background:rgba(127,127,127,.16); backdrop-filter:blur(16px) saturate(160%);
            box-shadow:0 8px 28px rgba(0,0,0,.28); font-size:13px; font-weight:400;
          }
          .menu .head{ padding:6px 8px 4px; font-size:11px; opacity:.6 }
          .menu button{
            width:100%; height:auto; padding:7px 8px; border:0; border-radius:8px;
            justify-content:flex-start; font-size:13px; font-weight:400; opacity:.9;
          }
          .spin{ animation:eco-spin 1s linear infinite; display:inline-flex }
          @media (max-width:1023px){ .lbl{ display:none } }
        </style>
        <button id="desk" title="Рабочий стол пространства">
          ${svg(ICONS.home)}<span class="lbl">Стол</span>
        </button>
        <button id="apps" aria-expanded="${this.#open}" title="Продукты пространства">
          ${this.#busy ? `<span class="spin">${svg(ICONS.apps)}</span>` : svg(ICONS.apps)}
          <span class="lbl">Приложения</span>
        </button>
        ${this.#open ? `
          <div class="menu">
            ${this.#apps === null ? '<div class="head">Загрузка…</div>' : ''}
            ${this.#apps && !this.#apps.length ? '<div class="head">Продукты недоступны</div>' : ''}
            <div class="head">${escapeHtml(label)}</div>
            ${(this.#apps || []).map((a) => `
              <button data-app="${escapeHtml(a.code)}">
                ${svg(a.mode === 'link' ? ICONS.external : ICONS.apps)}
                <span>${escapeHtml(a.name || a.code)}</span>
              </button>`).join('')}
          </div>` : ''}
      `

      root.getElementById('desk')?.addEventListener('click', () => location.assign(home))
      root.getElementById('apps')?.addEventListener('click', () => this.#toggle())
      root.querySelectorAll('[data-app]').forEach((el) => {
        const app = (this.#apps || []).find((a) => a.code === el.dataset.app)
        if (!app) return
        el.addEventListener('click', (e) => this.#openApp(app, wantsNewTab(e)))
        el.addEventListener('auxclick', (e) => { if (e.button === 1) this.#openApp(app, true) })
      })
    }
  }

  customElements.define('eco-apps', EcoApps)
})()
