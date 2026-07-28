/**
 * Пространство в приложениях ВНЕ Ledger: `<eco-apps>` — кнопки «Стол» и «Приложения»
 * в шапке, `<eco-nav>` — блок функций Ядра в левом меню (объекты, загрузка, документы,
 * контрагенты, база пространства, люди и доступ).
 *
 * Ядро отдаёт этот файл по адресу `/eco/rail.js` (nginx стека), приложение подключает
 * одной строкой и ставит элемент в СВОЮ шапку. Реализация одна на все приложения —
 * ванильный web-component, без React и без сборки, поэтому годится и для чужих фронтов.
 *
 * Раньше здесь жила ещё вертикальная колонка `<eco-rail>` у правого края. Её убрали:
 * она отнимала ширину, а после переезда на плавающую плашку — перекрывала шапку
 * приложения. Переходы дублировались с этими же кнопками, поэтому осталось одно место.
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
 * Кнопки — обычный inline-элемент внутри шапки приложения: ширины у страницы не
 * отнимают и ничего не перекрывают.
 */
;(() => {
  if (customElements.get('eco-apps')) return

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
    objects: '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    company: '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/>',
    network: '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
    map: '<path d="m15 5-6-3-6 3v16l6-3 6 3 6-3V2z"/><path d="M15 5v16"/><path d="M9 2v16"/>',
    book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"/>',
  }

  /**
   * Функции ЯДРА для левого меню приложения — тот же состав, что в рабочих местах Ledger
   * (`config/spaceProducts.ts` → SPACE_PAGES/SPACE_LINKS). Список продублирован намеренно:
   * этот файл ванильный, без сборки, а состав меняется реже, чем раз в релиз.
   */
  const SPACE_PAGES = [
    { path: '/objects', label: 'Объекты', icon: 'objects' },
    { path: '/intake', label: 'Загрузка', icon: 'upload' },
    { path: '/files', label: 'Документы', icon: 'file' },
    { path: '/contractors', label: 'Контрагенты', icon: 'company' },
  ]
  // Ядровые функции, живущие в другом приложении: гейт — его наличие в каталоге.
  const SPACE_LINKS = [
    { app: 'data', href: '/data?mode=normalize', label: 'База пространства', icon: 'network' },
    { app: 'admin', href: '/admin/company/map', label: 'Люди и доступ', icon: 'map' },
  ]
  // Рабочие места Ledger: страница Ядра открывается под адресом одного из них
  // (`/finance/objects`) — по адресу видно, откуда смотрят, и от этого зависят права.
  const WORKPLACES = ['projects', 'ops', 'sales', 'corp', 'shop', 'marketing', 'finance', 'data']

  // Продукты, у которых в шапке уже есть своя кнопка (Чат · Заявки · Конференция).
  // В списке «Приложения» их нет: один и тот же вход, названный дважды в двух соседних
  // местах, только удлиняет список. Тот же набор исключает лаунчер Ядра
  // (`services/ssoService.ts` → SIDE_BUTTON_APPS). На рабочем столе они остаются —
  // там витрина всего, что подключено компании.
  const SIDE_BUTTON_APPS = ['chat', 'plan', 'conf']

  const token = () => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  }

  /** Запрос к Ядру от имени уже вошедшего человека. Ошибку отдаём наверх — рельс её глотает. */
  async function core(path) {
    const t = token()
    if (!t) throw new Error('no token')
    // АБСОЛЮТНЫЙ адрес — обязательно. Приложение под префиксом (`/support`) ставит шим
    // на window.fetch и уводит любой относительный `/api/...` в свою базу
    // (`/support/api/...`), поэтому запрос к Ядру не доходил и каталог продуктов
    // приходил пустым — «Продукты недоступны». С origin шим путь не трогает.
    const r = await fetch(new URL(path, location.origin).href, {
      headers: { Authorization: `Bearer ${t}` },
    })
    if (!r.ok) throw new Error(String(r.status))
    return r.json()
  }

  /** Каталог продуктов — один запрос на страницу: его спрашивают и кнопки, и меню. */
  let appsPromise = null
  function loadApps() {
    if (!appsPromise) {
      appsPromise = core('/api/sso/apps')
        .then((d) => (d && d.enabled ? (d.apps || []) : []))
        .catch(() => [])
    }
    return appsPromise
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
      this.#apps = (await loadApps()).filter((a) => !SIDE_BUTTON_APPS.includes(a.code))
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
          /* Кнопки ПРОСТРАНСТВА намеренно нейтральные: рамка и цвет текста приложения,
             без заливки. Рядом стоят прикладные кнопки (Конференция · Чат · Заявки),
             и они синие — это действия внутри продукта. Навигация между продуктами
             не должна спорить с ними за внимание, поэтому у неё свой, тихий вид
             (решение МАГа 27.07.2026). Размеры при этом общие: высота 44, радиус 12. */
          button{
            display:inline-flex; align-items:center; gap:8px; height:44px; padding:0 12px;
            border-radius:12px; font:inherit; font-weight:500; font-size:14px; cursor:pointer;
            color:inherit; background:none; border:1px solid currentColor;
            opacity:.75; transition:opacity .2s, background .2s;
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
          /* Пункты списка — не пилюли: это строки меню, у них своя роль. */
          .menu button{
            width:100%; height:auto; padding:7px 8px; border:0; border-radius:8px;
            justify-content:flex-start; font-size:13px; font-weight:400;
            color:inherit; background:none;
          }
          .menu button:hover{ background:rgba(127,127,127,.18); color:inherit }
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

  /**
   * <eco-nav> — блок ЯДРА в левом меню приложения контейнера.
   *
   * Левое вертикальное меню — это меню пространства (решение МАГа 28.07.2026): сверху
   * разделы самого приложения, ниже — функции, которые идут от Ядра и одинаковы везде.
   * В рабочих местах Ledger блок рисует `AppSidebar`; приложениям вне Ledger (Поддержка)
   * его отдаёт Ядро этим компонентом — иначе человек, работающий в Поддержке, не может
   * ни загрузить договор, ни посмотреть, откуда взялись цифры, не выйдя из приложения.
   *
   *   <eco-nav></eco-nav>              // в самом низу своей колонки меню
   *   <eco-nav collapsed></eco-nav>    // свёрнутая колонка: только иконки
   *
   * Состав фильтруется правами: каталог `/api/sso/apps` уже отдаёт только то, что роль
   * разрешила и что подключено компании. Нет ни одного рабочего места Ledger — страницы
   * Ядра не показываем: они всё равно закрыты. Нет токена Ядра (вход прямой формой
   * приложения) — компонент не рисует ничего.
   */
  class EcoNav extends HTMLElement {
    #items = null

    static observedAttributes = ['collapsed', 'label']

    connectedCallback() {
      this.render()
      loadApps().then((apps) => {
        const codes = apps.map((a) => a.code)
        // Страницы Ядра открываются под адресом рабочего места — берём первое доступное.
        const host = apps.find((a) => WORKPLACES.includes(a.code) && a.route)
        this.#items = [
          ...(host ? SPACE_PAGES.map((p) => ({ ...p, href: `${host.route}${p.path}` })) : []),
          ...SPACE_LINKS.filter((l) => codes.includes(l.app)),
        ]
        this.render()
      })
    }

    attributeChangedCallback() { if (this.#items) this.render() }

    render() {
      const root = this.shadowRoot ?? this.attachShadow({ mode: 'open' })
      const collapsed = this.hasAttribute('collapsed')
      const label = this.getAttribute('label') || 'Пространство'
      // Пустой блок не должен оставлять после себя ни отступа, ни разделителя: у роли
      // без доступа к Ledger в колонке приложения просто ничего не меняется.
      const empty = !token() || !this.#items || !this.#items.length
      this.style.display = empty ? 'none' : ''
      if (empty) { root.innerHTML = ''; return }

      root.innerHTML = `
        <style>
          :host{ display:block; font:inherit; color:inherit }
          /* Заголовок блока — 12px при .75: на 11px и .55 подпись читал только тот,
             кто знал, что она там есть (контраст ниже порога AA). Разделителя сверху
             больше нет: в отдельной колонке пространства отделять не от чего. */
          .head{ padding:8px 12px; font-size:12px; font-weight:600; letter-spacing:.08em;
                 text-transform:uppercase; opacity:.75 }
          a{ display:flex; align-items:center; gap:12px; padding:8px 12px; margin:1px 0;
             border-radius:6px; font-size:14px; font-weight:500; text-decoration:none;
             color:inherit; opacity:.85; transition:opacity .15s, background .15s }
          a:hover{ opacity:1; background:rgba(127,127,127,.14) }
          a.narrow{ justify-content:center; padding:8px 0 }
          svg{ width:16px; height:16px; flex:none }
        </style>
        ${collapsed ? '' : `<div class="head">${escapeHtml(label)}</div>`}
        ${this.#items.map((i) => `
          <a href="${escapeHtml(i.href)}" class="${collapsed ? 'narrow' : ''}" title="${escapeHtml(i.label)}">
            ${svg(ICONS[i.icon])}${collapsed ? '' : `<span>${escapeHtml(i.label)}</span>`}
          </a>`).join('')}
      `
    }
  }

  customElements.define('eco-nav', EcoNav)

  /**
   * `<eco-info>` — кнопка «Инфо» и контекстная панель знания пространства.
   *
   * Стандарт один на все приложения контейнера (docs/INFO.md): человек видит
   * подсказку там, где работает, а не ищет её в отдельном приложении. Ядро
   * отвечает за содержание, приложение — только за место кнопки в своей шапке:
   *
   *   <eco-info app="support" section="tickets"></eco-info>
   *
   * `app`     — код продукта в реестре пространства (обязателен);
   * `section` — ключ раздела рабочей области, если приложение умеет его назвать.
   *
   * Панель — оверлей справа внутри теневого дерева: чужие стили её не ломают, а
   * она не ломает вёрстку приложения. Нет токена Ядра — кнопки нет вовсе.
   */
  class EcoInfo extends HTMLElement {
    #open = false
    #items = null
    #article = null
    #loading = false

    static observedAttributes = ['app', 'section', 'label']

    connectedCallback() { this.render() }

    attributeChangedCallback(name) {
      // Сменилась рабочая область — подборка устарела, тянем заново при открытии.
      if (name === 'app' || name === 'section') { this.#items = null; this.#article = null }
      this.render()
    }

    async #load() {
      const app = this.getAttribute('app')
      if (!app || this.#loading) return
      this.#loading = true
      this.render()
      try {
        const section = this.getAttribute('section')
        const qs = new URLSearchParams({ app_code: app })
        if (section) qs.set('section_key', section)
        const d = await core(`/api/info/context?${qs}`)
        this.#items = d && d.items ? d.items : []
      } catch { this.#items = [] }
      this.#loading = false
      this.render()
    }

    async #openArticle(id) {
      this.#loading = true; this.render()
      try { this.#article = await core(`/api/info/articles/${id}`) } catch { this.#article = null }
      this.#loading = false
      this.render()
    }

    #toggle() {
      this.#open = !this.#open
      this.#article = null
      if (this.#open && this.#items === null) this.#load()
      else this.render()
    }

    render() {
      const root = this.shadowRoot ?? this.attachShadow({ mode: 'open' })
      // Без токена Ядра знание недоступно: человек вошёл прямой формой приложения.
      if (!token() || !this.getAttribute('app')) { this.style.display = 'none'; root.innerHTML = ''; return }
      this.style.display = ''
      const label = this.getAttribute('label') || 'Инфо'
      const items = this.#items || []
      const a = this.#article

      root.innerHTML = `
        <style>
          :host{ display:inline-flex; font:inherit; color:inherit }
          button.b{ display:inline-flex; align-items:center; gap:8px; padding:8px 12px;
                    border-radius:10px; border:1px solid rgba(127,127,127,.35);
                    background:transparent; color:inherit; font:inherit; font-size:14px;
                    cursor:pointer; transition:background .15s }
          button.b:hover{ background:rgba(127,127,127,.14) }
          .scrim{ position:fixed; inset:0; background:rgba(0,0,0,.35); z-index:2147483000 }
          .panel{ position:fixed; top:0; right:0; bottom:0; width:min(420px,100vw);
                  background:var(--eco-info-bg,#fff); color:inherit; z-index:2147483001;
                  display:flex; flex-direction:column; box-shadow:-8px 0 24px rgba(0,0,0,.18) }
          @media (prefers-color-scheme: dark){ .panel{ background:var(--eco-info-bg,#0f1115) } }
          .head{ display:flex; align-items:center; gap:8px; padding:10px 12px;
                 border-bottom:1px solid rgba(127,127,127,.25); font-size:13px; font-weight:600 }
          .head button{ background:none; border:0; color:inherit; cursor:pointer; opacity:.6; font-size:16px }
          .body{ flex:1; overflow-y:auto; padding:12px; font-size:13px; line-height:1.55 }
          .card{ display:block; width:100%; text-align:left; margin:0 0 8px; padding:8px 10px;
                 border:1px solid rgba(127,127,127,.28); border-radius:8px; background:transparent;
                 color:inherit; font:inherit; cursor:pointer }
          .card:hover{ border-color:rgba(80,130,255,.6) }
          .t{ font-weight:600; font-size:13px }
          .s{ opacity:.7; font-size:12px; margin-top:2px }
          .m{ opacity:.55; font-size:11px; margin-top:2px }
          .empty{ opacity:.7; font-size:12px }
          svg{ width:16px; height:16px; flex:none }
          pre{ white-space:pre-wrap; font:inherit }
        </style>
        <button class="b" part="button" title="${escapeHtml(label)}">
          ${svg(ICONS.book)}<span>${escapeHtml(label)}</span>
        </button>
        ${this.#open ? `
          <div class="scrim" data-close></div>
          <aside class="panel" role="dialog" aria-label="Инфо">
            <div class="head">
              ${a ? '<button data-back title="Назад">‹</button>' : ''}
              <span style="flex:1">${a ? escapeHtml(a.title) : escapeHtml(label)}</span>
              <button data-close title="Закрыть">✕</button>
            </div>
            <div class="body">
              ${this.#loading ? '<div class="empty">загружаем…</div>' : a
                ? `<div class="m">${escapeHtml(a.kindLabel || '')}${a.docNumber ? ' · ' + escapeHtml(a.docNumber) : ''}</div><pre>${escapeHtml(a.bodyMd || '')}</pre>`
                : items.length
                  ? items.map((i) => `
                      <button class="card" data-id="${escapeHtml(i.id)}">
                        <span class="t">${escapeHtml(i.title)}</span>
                        ${i.summary ? `<span class="s">${escapeHtml(i.summary)}</span>` : ''}
                        <span class="m">${escapeHtml(i.kindLabel || '')}${i.exact ? ' · этот раздел' : ''}</span>
                      </button>`).join('')
                  : '<div class="empty">Для этой рабочей области пояснений пока нет. Знание пространства ведётся в приложении «Инфо».</div>'}
            </div>
          </aside>` : ''}
      `
      root.querySelector('button.b').onclick = () => this.#toggle()
      root.querySelectorAll('[data-close]').forEach((el) => { el.onclick = () => this.#toggle() })
      const back = root.querySelector('[data-back]')
      if (back) back.onclick = () => { this.#article = null; this.render() }
      root.querySelectorAll('.card').forEach((el) => {
        el.onclick = () => this.#openArticle(el.getAttribute('data-id'))
      })
    }
  }

  customElements.define('eco-info', EcoInfo)
})()
