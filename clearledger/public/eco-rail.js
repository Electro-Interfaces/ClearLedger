/**
 * Пространство в приложениях ВНЕ Ledger: `<eco-nav>` — блок Ядра в левом меню
 * (пункт «Приложения» и функции Ядра: объекты, загрузка, документы, контрагенты,
 * база пространства, люди и доступ), `<eco-info>` — контекстная подсказка.
 *
 * Ядро отдаёт этот файл по адресу `/eco/rail.js` (nginx стека), приложение подключает
 * одной строкой и ставит элемент в СВОЮ колонку меню. Реализация одна на все
 * приложения — ванильный web-component, без React и без сборки, поэтому годится и
 * для чужих фронтов.
 *
 *   <script defer src="/eco/rail.js"></script>
 *   <eco-nav></eco-nav>                  // в своей колонке меню
 *
 * ВХОД В ПРОСТРАНСТВО ОДИН — пункт «Приложения» в меню (решение МАГа 06.08.2026).
 * До этого было три места: вертикальная колонка `<eco-rail>` у правого края (убрана —
 * отнимала ширину и перекрывала шапку), затем пара кнопок «Стол» и «Приложения» в
 * шапке (`<eco-apps>`, убрана — уводила со страницы ради того, чтобы просто посмотреть
 * состав пространства). Теперь пункт меню открывает плашки ПОВЕРХ текущего экрана,
 * переход — только по плашке, а рабочий стол стал первой из них.
 *
 * ВИТРИНА ОДНА. Плашки продуктов рисует НЕ этот файл: панель показывает фреймом стол
 * Ядра во встроенном виде (`/apps` → `EcosystemHomePage embedded`). До 06.09.2026 здесь
 * лежала своя разметка плиток, и она отставала от стола на несколько решений: в
 * Поддержке не было ни выбора «карточки или список», ни избранного, ни переносимых
 * строк, а карта готовности продуктов существовала во второй копии. Теперь каталог,
 * слои, избранное и вид — одни на всё пространство, где бы панель ни открылась.
 *
 * КАТАЛОГ. Продукты берутся из единого реестра Ядра (`GET /api/sso/apps`) — того же,
 * что питает рабочий стол Ledger, поэтому отключённый в «Управлении» продукт исчезает
 * и здесь. Приложения контейнера живут на ОДНОМ origin (docs/CORE.md §6), значит токен
 * Ядра лежит в том же localStorage — им и авторизуемся. Токена нет (человек вошёл
 * прямой формой приложения, минуя Ядро) или каталог не ответил — блока просто не
 * будет: Ядро не должно ломать приложение.
 */
;(() => {
  if (customElements.get('eco-nav')) return

  // База Ядра — от адреса этого файла (`<база>/eco/rail.js`): на стенде показа
  // пространство отдаётся под /demo-run/<стенд>/app/, и корень там не корень.
  const CORE_BASE = (document.currentScript && document.currentScript.src || '/eco/rail.js')
    .replace(/eco\/rail\.js.*$/, '')

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

  const token = () => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  }

  /** Email из JWT Ядра (клейм `email`). Не разобрали — пусто, сверять нечем. */
  const jwtEmail = (t) => {
    try {
      const p = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
      const j = JSON.parse(atob(p.padEnd(Math.ceil(p.length / 4) * 4, '=')))
      return String(j.email || '').trim().toLowerCase()
    } catch { return '' }
  }

  /**
   * ЧУЖОЙ СЕАНС ЯДРА. Приложения контейнера живут на одном origin, поэтому токен Ядра
   * общий — но сеанс приложения свой. Человек, вошедший прямой формой приложения после
   * того, как в этом браузере работал кто-то другой, получал рельсу ПРЕДЫДУЩЕГО: панель
   * показывала его каталог приложений, а переход по плитке шёл его handoff-токеном и
   * сажал в его учётную запись (04.09.2026, оператор контакт-центра видел всё
   * пространство и попадал в чужую Поддержку).
   *
   * Хозяин страницы сообщает свою личность атрибутом `user`; не сообщил — поведение
   * прежнее. Чужой токен не трогаем: это сеанс Ядра, гасить его нам не по чину, —
   * просто не показываем ничего от его имени.
   */
  const alienSession = (el) => {
    const host = (el.getAttribute('user') || '').trim().toLowerCase()
    const t = token()
    if (!host || !t) return false
    const mine = jwtEmail(t)
    return !!mine && mine !== host
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

  // Имя продукта приходит из реестра, где его вводит админ, а рисуем мы через innerHTML.
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ))

  const svg = (paths) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`

  /**
   * Границы рабочей области приложения для панели.
   *
   * Приложение помечает свой контейнер атрибутом data-eco-workarea. Без пометки
   * возвращаем прежнее «на весь экран»: рельс работает в чужих приложениях, и молча
   * промахнуться мимо области хуже, чем открыться поверх всего.
   */
  const workareaBox = () => {
    // Помеченных кусков может быть несколько: в приложении с двумя колонками меню
    // область это меню продукта ПЛЮС страница. Панель обязана накрыть оба — иначе
    // рядом с карточками продуктов остаётся висеть меню того, из чего человек уходит.
    const areas = [...document.querySelectorAll('[data-eco-workarea]')]
      .map((el) => el.getBoundingClientRect())
      .filter((r) => r.width && r.height)
    if (!areas.length) return 'inset:0;'
    const top = Math.min(...areas.map((r) => r.top))
    const left = Math.min(...areas.map((r) => r.left))
    const right = Math.max(...areas.map((r) => r.right))
    const bottom = Math.max(...areas.map((r) => r.bottom))
    return `top:${Math.round(top)}px; left:${Math.round(left)}px;` +
           ` width:${Math.round(right - left)}px; height:${Math.round(bottom - top)}px;`
  }

  /**
   * Фон и цвет текста САМОЙ страницы — для непрозрачной панели поверх приложения.
   *
   * Тему задаёт приложение (класс `dark` на корне), а не системная настройка, поэтому
   * `prefers-color-scheme` врёт: на тёмной Поддержке при светлой системе панель выходила
   * белой, а текст наследовался светлый. Берём вычисленные цвета у body, при прозрачном
   * фоне поднимаемся к html, и только в самом крайнем случае — светлая пара.
   */
  const colorOk = (v) => !!v && /^(rgb|hsl|#)/.test(v) && !/rgba?\([^)]*,\s*0\s*\)/.test(v)
  function pageColors() {
    const b = getComputedStyle(document.body)
    const h = getComputedStyle(document.documentElement)
    return {
      bg: colorOk(b.backgroundColor) ? b.backgroundColor
        : colorOk(h.backgroundColor) ? h.backgroundColor : '#ffffff',
      fg: colorOk(b.color) ? b.color : '#111111',
    }
  }

  /** Тёмный ли фон: берём среднюю яркость первых трёх чисел из rgb()/rgba(). */
  const isDark = (bg) => {
    const n = String(bg).match(/\d+(\.\d+)?/g)
    if (!n || n.length < 3) return false
    return (Number(n[0]) + Number(n[1]) + Number(n[2])) / 3 < 128
  }

  /** Переход в продукт пространства: внутренний — по адресу, чужой — через ключ Ядра. */
  async function openApp(app, newTab, onBusy) {
    if (app.mode === 'internal' && app.route) {
      if (newTab) window.open(app.route, '_blank', 'noopener,noreferrer')
      else location.assign(app.route)
      return
    }
    onBusy(app.code)
    try {
      const r = await core(`/api/sso/authorize?app=${encodeURIComponent(app.code)}`)
      if (newTab || !sameOrigin(r.url)) window.open(r.url, '_blank', 'noopener,noreferrer')
      else location.assign(r.url)
    } catch {
      /* переход между продуктами не должен ронять приложение */
    } finally {
      onBusy(null)
    }
  }


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
   * ПУНКТ «ПРИЛОЖЕНИЯ» — первый в блоке (решение МАГа 06.08.2026). Он не уводит со
   * страницы: показывает плашки продуктов ПОВЕРХ текущего экрана, переход происходит
   * только по плашке. Раньше на его месте в ШАПКЕ стояли две кнопки, «Стол» и
   * «Приложения» (`<eco-apps>`): чтобы просто посмотреть состав пространства,
   * человек покидал свою работу. Компонент шапки убран, рабочий стол стал первой
   * плашкой панели — вход в пространство остался один и там же, где в Ledger.
   *
   * Состав фильтруется правами: каталог `/api/sso/apps` уже отдаёт только то, что роль
   * разрешила и что подключено компании. Нет ни одного рабочего места Ledger — страницы
   * Ядра не показываем: они всё равно закрыты. Нет токена Ядра (вход прямой формой
   * приложения) — компонент не рисует ничего.
   *
   * Атрибуты: `collapsed` (только иконки), `label` (подпись блока), `home` (адрес
   * рабочего стола, по умолчанию «/»).
   */
  class EcoNav extends HTMLElement {
    #items = null
    #open = false

    static observedAttributes = ['collapsed', 'label', 'part', 'user']

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
      this.onKey = (e) => { if (e.key === 'Escape') this.#close() }
      document.addEventListener('keydown', this.onKey)
      // Границы области померены в момент открытия, поэтому при смене размеров окна
      // панель надо переложить, иначе она уедет с рабочей области
      this.onResize = () => { if (this.#open) this.#place() }
      window.addEventListener('resize', this.onResize)
      // Уход по любому пункту меню закрывает панель: человек выбрал, куда идти, и
      // держать карточки поверх нового экрана незачем. Клики внутри самого рельса
      // (кнопка «Приложения», плитки, затемнение) разбираются своими обработчиками.
      this.onDocClick = (e) => {
        if (!this.#open) return
        const path = typeof e.composedPath === 'function' ? e.composedPath() : []
        if (!path.includes(this)) this.#close()
      }
      document.addEventListener('click', this.onDocClick)
      // Навигация без клика (назад-вперёд, переход из кода) — тот же случай
      this.onNav = () => this.#close()
      window.addEventListener('popstate', this.onNav)
    }

    disconnectedCallback() {
      document.removeEventListener('keydown', this.onKey)
      window.removeEventListener('resize', this.onResize)
      document.removeEventListener('click', this.onDocClick)
      window.removeEventListener('popstate', this.onNav)
    }

    #close() { if (this.#open) { this.#open = false; this.render() } }

    /** Переложить открытую панель по рабочей области — без перерисовки разметки:
     *  новый innerHTML пересоздал бы фрейм витрины, и она грузилась бы заново. */
    #place() {
      const root = this.shadowRoot
      if (!root) return
      const box = workareaBox()
      root.querySelectorAll('.scrim, .panel').forEach((el) => { el.style.cssText = box })
    }

    attributeChangedCallback() { if (this.#items) this.render() }

    render() {
      const root = this.shadowRoot ?? this.attachShadow({ mode: 'open' })
      const collapsed = this.hasAttribute('collapsed')
      // part: 'apps' — только вход в приложения и рабочий стол, 'pages' — только
      // страницы Ядра. Без атрибута рисуем всё одним блоком, как раньше.
      const part = this.getAttribute('part') || 'all'
      const showApps = part !== 'pages'
      const showPages = part !== 'apps'
      const label = this.getAttribute('label') || 'Пространство'
      const items = this.#items || []
      const { bg, fg } = pageColors()
      // Витрина внутри фрейма одевается по ХОЗЯИНУ, а не по своей настройке: тема
      // Ядра лежит в общем localStorage и у человека может быть светлой, а Поддержка
      // всегда тёмная — светлая панель в тёмном приложении выглядит чужой страницей.
      const dark = isDark(bg)
      const box = workareaBox()
      // Без токена Ядра человек вошёл прямой формой приложения: ни страниц Ядра, ни
      // перехода в соседний продукт ему показывать не на чем. Блок исчезает целиком,
      // не оставляя ни отступа, ни разделителя.
      const off = !token() || alienSession(this)
      this.style.display = off ? 'none' : ''
      if (off) { root.innerHTML = ''; return }

      root.innerHTML = `
        <style>
          :host{ display:block; font:inherit; color:inherit }
          /* Заголовок блока — 12px при .75: на 11px и .55 подпись читал только тот,
             кто знал, что она там есть (контраст ниже порога AA). Разделителя сверху
             больше нет: в отдельной колонке пространства отделять не от чего. */
          .head{ padding:8px 12px; font-size:12px; font-weight:600; letter-spacing:.08em;
                 text-transform:uppercase; opacity:.75 }
          a, button.nav{ display:flex; align-items:center; gap:12px; width:100%; padding:8px 12px;
             margin:1px 0; box-sizing:border-box; border:0; border-radius:6px; font:inherit;
             font-size:14px; font-weight:500; text-align:left; text-decoration:none; cursor:pointer;
             color:inherit; background:none; opacity:.85; transition:opacity .15s, background .15s }
          a:hover, button.nav:hover{ opacity:1; background:rgba(127,127,127,.14) }
          button.nav[aria-expanded="true"]{ opacity:1; background:rgba(127,127,127,.18) }
          a.narrow, button.narrow{ justify-content:center; padding:8px 0 }
          /* Разделитель под «Приложениями»: ниже — функции Ядра, это другой род пунктов. */
          .sep{ height:1px; margin:6px 8px; background:rgba(127,127,127,.28) }
          svg{ width:16px; height:16px; flex:none }
          /* Панель приложений — поверх страницы, а не вместо неё: экран под ней
             остаётся на месте, человек возвращается к работе закрытием.
             Панель занимает рабочую область приложения, а не всё окно: шапка и меню
             остаются на виду и кликабельны, как на рабочем столе Ядра. Границы берём
             у элемента с data-eco-workarea; приложение без такой пометки получает
             прежнее поведение на весь экран (см. workareaBox), и ставятся они
             отдельным стилем — при смене размеров окна панель перекладывается, а
             фрейм витрины при этом не перезагружается.
             Фон берём У САМОЙ СТРАНИЦЫ (см. pageColors), а не у prefers-color-scheme:
             тема приложения задаётся его же классом, и на тёмной Поддержке при светлой
             системной теме панель выходила белой со светлым текстом. */
          .scrim{ position:fixed; z-index:2147483000; background:rgba(0,0,0,.45);
                  backdrop-filter:blur(4px) }
          .panel{ position:fixed; z-index:2147483001; display:flex; flex-direction:column;
                  box-sizing:border-box; background:${bg}; color:${fg} }
          .ptop{ display:flex; align-items:flex-start; gap:12px; width:100%;
                 padding:10px 16px;
                 border-bottom:1px solid rgba(127,127,127,.25) }
          .ptitle{ flex:1; min-width:0 }
          .ptitle b{ display:block; font-size:14px; font-weight:600 }
          .ptitle span{ font-size:12px; opacity:.7 }
          .px{ border:0; background:none; color:inherit; font:inherit; font-size:18px;
               line-height:1; padding:6px; border-radius:8px; cursor:pointer; opacity:.6 }
          .px:hover{ opacity:1; background:rgba(127,127,127,.16) }
          /* Витрина — стол Ядра во встроенном виде. Своей разметки плиток у панели
             нет: каталог, слои, избранное и вид «карточки/список» одни на всё
             пространство (src/pages/EcosystemHomePage.tsx). */
          .apps{ flex:1; width:100%; border:0; background:transparent }
        </style>
        ${showPages && !collapsed && showApps ? `<div class="head">${escapeHtml(label)}</div>` : ''}
        ${showApps ? `
          <button class="nav ${collapsed ? 'narrow' : ''}" id="apps" aria-expanded="${this.#open}"
                  title="Приложения пространства">
            ${svg(ICONS.apps)}
            ${collapsed ? '' : '<span>Приложения</span>'}
          </button>
` : ''}
        ${showPages && showApps && items.length ? '<div class="sep"></div>' : ''}
        ${showPages && !showApps && !collapsed && items.length
          ? `<div class="head">${escapeHtml(label)}</div>` : ''}
        ${showPages ? items.map((i) => `
          <a href="${escapeHtml(i.href)}" class="${collapsed ? 'narrow' : ''}" title="${escapeHtml(i.label)}">
            ${svg(ICONS[i.icon])}${collapsed ? '' : `<span>${escapeHtml(i.label)}</span>`}
          </a>`).join('') : ''}
        ${this.#open ? `
          <div class="scrim" data-close style="${box}"></div>
          <section class="panel" role="dialog" aria-label="Приложения пространства" style="${box}">
            <div class="ptop">
              <div class="ptitle">
                <b>Приложения пространства</b>
                <span>Выберите, куда перейти — экран под панелью останется на месте</span>
              </div>
              <button class="px" data-close title="Закрыть">✕</button>
            </div>
            <iframe class="apps" title="Приложения пространства"
                    src="${CORE_BASE}apps?theme=${dark ? 'dark' : 'light'}"></iframe>
          </section>` : ''}
      `

      const appsBtn = root.getElementById('apps')
      if (appsBtn) appsBtn.onclick = () => { this.#open = !this.#open; this.render() }
      root.querySelectorAll('[data-close]').forEach((el) => { el.onclick = () => this.#close() })
    }
  }

  /**
   * Переход в приложение пространства по коду — для кнопок самого приложения.
   *
   * Кнопке «Задачи» в шапке Поддержки нужен тот же переход, что и плитке в панели:
   * внутренний маршрут или обмен через handoff, смотря как продукт подключён. Класть
   * адрес в приложение нельзя — он живёт в реестре Ядра и там же меняется.
   */
  window.ecoOpenApp = async (code, newTab) => {
    const app = (await loadApps()).find((a) => a.code === code)
    if (!app) return false
    await openApp(app, Boolean(newTab), () => {})
    return true
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

    static observedAttributes = ['app', 'section', 'label', 'user']

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
      if (!token() || !this.getAttribute('app') || alienSession(this)) {
        this.style.display = 'none'; root.innerHTML = ''; return
      }
      this.style.display = ''
      const label = this.getAttribute('label') || 'Инфо'
      const items = this.#items || []
      const a = this.#article

      root.innerHTML = `
        <style>
          :host{ display:inline-flex; font:inherit; color:inherit }
          button.b{ display:inline-flex; align-items:center; gap:8px; height:44px; padding:0 12px;
                    border-radius:12px; border:1px solid rgba(59,123,255,.3);
                    background:rgba(59,123,255,.1); color:#5b8cff; font:inherit; font-size:14px;
                    font-weight:500; cursor:pointer; transition:background .2s, color .2s, border-color .2s }
          button.b:hover{ background:#3b7bff; border-color:#3b7bff; color:#fff }
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
