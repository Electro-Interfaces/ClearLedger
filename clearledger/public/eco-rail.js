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
 * КАТАЛОГ. Продукты берутся из единого реестра Ядра (`GET /api/sso/apps`) — того же,
 * что питает рабочий стол Ledger, поэтому отключённый в «Управлении» продукт исчезает
 * и здесь. Приложения контейнера живут на ОДНОМ origin (docs/CORE.md §6), значит токен
 * Ядра лежит в том же localStorage — им и авторизуемся. Токена нет (человек вошёл
 * прямой формой приложения, минуя Ядро) или каталог не ответил — блока просто не
 * будет: Ядро не должно ломать приложение.
 */
;(() => {
  if (customElements.get('eco-nav')) return

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
        .then((d) => {
          // Профиль решает готовность части продуктов: у розницы топлива «Магазин»
          // рабочий, у энергетики заготовка. Ядро отдаёт профиль не всегда — без него
          // берём базовую карту, как стол до появления профилей.
          if (d && d.profile_id) profileId = d.profile_id
          return d && d.enabled ? (d.apps || []) : []
        })
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

  /**
   * Иконки продуктов по имени из реестра Ядра (`eco_apps.icon`). Разметка снята с тех же
   * иконок lucide, которыми рисует стол: одинаковая иконка на всех плитках делала панель
   * нечитаемой, продукт узнавался только по названию.
   */
  const PRODUCT_ICONS = {
    'life-buoy': '<circle cx="12" cy="12" r="10"/><path d="m4.93 4.93 4.24 4.24"/><path d="m14.83 9.17 4.24-4.24"/><path d="m14.83 14.83 4.24 4.24"/><path d="m9.17 14.83-4.24 4.24"/><circle cx="12" cy="12" r="4"/>',
    'clipboard-list': '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/>',
    'list-checks': '<path d="M13 5h8"/><path d="M13 12h8"/><path d="M13 19h8"/><path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/>',
    'video': '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
    'file-text': '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    'messages-square': '<path d="M16 10a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 14.286V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/><path d="M20 9a2 2 0 0 1 2 2v10.286a.71.71 0 0 1-1.212.502l-2.202-2.202A2 2 0 0 0 17.172 19H10a2 2 0 0 1-2-2v-1"/>',
    'message-circle': '<path d="M2.992 16.342a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168l3.413-.998a2 2 0 0 1 1.099.092 10 10 0 1 0-4.777-4.719"/>',
    'shield-check': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    'book-open': '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
    'activity': '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    'hard-hat': '<path d="M10 10V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v5"/><path d="M14 6a6 6 0 0 1 6 6v3"/><path d="M4 15v-3a6 6 0 0 1 6-6"/><rect x="2" y="15" width="20" height="4" rx="1"/>',
    'gauge': '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    'bar-chart-3': '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    'wallet': '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    'database': '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    'building-2': '<path d="M10 12h4"/><path d="M10 8h4"/><path d="M14 21v-3a2 2 0 0 0-4 0v3"/><path d="M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2"/><path d="M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/>',
    'shopping-cart': '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
    'megaphone': '<path d="M11 6a13 13 0 0 0 8.4-2.8A1 1 0 0 1 21 4v12a1 1 0 0 1-1.6.8A13 13 0 0 0 11 14H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/><path d="M6 14a12 12 0 0 0 2.4 7.2 2 2 0 0 0 3.2-2.4A8 8 0 0 1 10 14"/><path d="M8 6v8"/>',
    'network': '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
    'calculator': '<rect width="16" height="20" x="4" y="2" rx="2"/><line x1="8" x2="16" y1="6" y2="6"/><line x1="16" x2="16" y1="14" y2="18"/><path d="M16 10h.01"/><path d="M12 10h.01"/><path d="M8 10h.01"/><path d="M12 14h.01"/><path d="M8 14h.01"/><path d="M12 18h.01"/><path d="M8 18h.01"/>',
    'stethoscope': '<path d="M11 2v2"/><path d="M5 2v2"/><path d="M5 3H4a2 2 0 0 0-2 2v4a6 6 0 0 0 12 0V5a2 2 0 0 0-2-2h-1"/><path d="M8 15a6 6 0 0 0 12 0v-3"/><circle cx="20" cy="10" r="2"/>',
    'layout-grid': '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
  }

  /**
   * Готовность продукта — точка на плитке: зелёная рабочий, жёлтая в развитии,
   * красная в подключении.
   *
   * КОПИЯ карты из `src/config/spaceProducts.ts` (PRODUCT_READINESS + READINESS_BY_PROFILE).
   * Рельс это статика, импортировать TS ему нечем, поэтому карта продублирована, а
   * расхождение ловит `scripts/eco-rail-smoke.mjs`: он читает оба файла и падает, если
   * состояния разъехались. Правится в spaceProducts.ts, сюда переносится следом.
   */
  const READINESS = {
    admin: 'ready', data: 'partial', info: 'partial', pulse: 'partial',
    chat: 'ready', plan: 'partial', conf: 'ready',
    projects: 'ready', ops: 'partial', sales: 'ready',
    corp: 'draft', shop: 'draft', marketing: 'partial',
    support: 'ready', finance: 'draft',
    netlink: 'draft', accounting: 'draft', diag: 'draft',
    monitor: 'ready', processing: 'ready',
  }
  const READINESS_BY_PROFILE = {
    fuel: { sales: 'ready', shop: 'ready', finance: 'ready', ops: 'draft', data: 'partial' },
  }
  const READINESS_LABEL = { ready: 'рабочий продукт', partial: 'в развитии', draft: 'в подключении' }
  const DOT_COLOR = { ready: '#10b981', partial: '#fbbf24', draft: '#ef4444' }
  let profileId = null
  const readinessOf = (code) =>
    (profileId && READINESS_BY_PROFILE[profileId] && READINESS_BY_PROFILE[profileId][code])
    || READINESS[code]

  const svg = (paths) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`

  /**
   * Слои продуктов: те же группы и в том же порядке, что на рабочем столе Ядра.
   *
   * Раскладка идёт по слою каталога (`layer`), а торговый контур вынесен отдельно —
   * «Поддержка» числится сервисом, но работают с ней в одном ряду с продажами,
   * и на столе она стоит именно там. Панель в приложении обязана повторять стол:
   * иначе человек ищет продукт в двух местах и находит в разных группах.
   */
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

  /* Раскладка стола: коды и порядок повторяют EcosystemHomePage Ядра. Слой каталога
     говорит, ЧТО это, но место задаёт рабочий контур: «Поддержка» числится сервисом,
     «Диагностика» ядром, а работают с ними в одной строке дня. */
  const COMMERCE = [
    'support', 'sales', 'projects', 'netlink', 'diag',
    'shop', 'corp', 'marketing', 'monitor', 'processing',
  ]
  const LEAD = ['pulse']
  const INTERNAL_ORDER = ['ops', 'finance', 'accounting']

  const layersOf = (apps) => {
    const all = apps || []
    const management = all.filter((a) => a.layer === 'admin' && !COMMERCE.includes(a.code))
    const services = all.filter((a) => a.layer === 'service' && !COMMERCE.includes(a.code))
    const products = all.filter((a) => COMMERCE.includes(a.code)
      || (a.layer !== 'admin' && a.layer !== 'service'))
    const lead = products.filter((a) => LEAD.includes(a.code))
    // Порядок рабочей строки задан явно, а не порядком реестра
    const commerce = COMMERCE.map((code) => products.find((a) => a.code === code)).filter(Boolean)
    const internal = products
      .filter((a) => !COMMERCE.includes(a.code) && !LEAD.includes(a.code))
      .sort((a, b) => {
        const ia = INTERNAL_ORDER.indexOf(a.code), ib = INTERNAL_ORDER.indexOf(b.code)
        return (ia < 0 ? INTERNAL_ORDER.length : ia) - (ib < 0 ? INTERNAL_ORDER.length : ib)
      })
    return [
      { title: 'Руководство', hint: 'как идут дела и куда вмешаться', items: lead },
      { title: 'Клиенты и продажи', hint: 'кому продаём и как обслуживаем', items: commerce },
      { title: 'Сеть и учёт', hint: 'чем владеем и как считаем', items: internal },
      { title: 'Сервисы экосистемы', hint: 'общие для всех приложений', items: services },
      { title: 'Ядро системы', hint: '', items: management },
    ].filter((group) => group.items.length)
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
    #apps = null
    #open = false
    #busy = null

    static observedAttributes = ['collapsed', 'label', 'part']

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
        // Чат · Задачи · Конференции показываем, хотя они же стоят кнопками в шапке:
        // на столе Ядра они есть, а панель обязана повторять стол. Прятать их значило
        // показывать в приложении не тот состав пространства, что на столе.
        this.#apps = apps
        this.render()
      })
      this.onKey = (e) => { if (e.key === 'Escape') this.#close() }
      document.addEventListener('keydown', this.onKey)
      // Границы области померены в момент открытия, поэтому при смене размеров окна
      // панель надо переложить, иначе она уедет с рабочей области
      this.onResize = () => { if (this.#open) this.render() }
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
      const home = this.getAttribute('home') || '/'
      const items = this.#items || []
      const { bg, fg } = pageColors()
      const box = workareaBox()
      // Без токена Ядра человек вошёл прямой формой приложения: ни страниц Ядра, ни
      // перехода в соседний продукт ему показывать не на чем. Блок исчезает целиком,
      // не оставляя ни отступа, ни разделителя.
      this.style.display = token() ? '' : 'none'
      if (!token()) { root.innerHTML = ''; return }

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
             Фон и цвет берём У САМОЙ СТРАНИЦЫ (см. pageColors), а не у
             prefers-color-scheme: тема приложения задаётся его же классом, и на тёмной
             Поддержке при светлой системной теме панель выходила белой со светлым
             текстом — читать было нечего. */
          /* Панель занимает рабочую область приложения, а не всё окно: шапка и меню
             остаются на виду и кликабельны, как на рабочем столе Ядра. Границы берём
             у элемента с data-eco-workarea; приложение без такой пометки получает
             прежнее поведение на весь экран. */
          .scrim{ position:fixed; ${box} z-index:2147483000; background:rgba(0,0,0,.45);
                  backdrop-filter:blur(4px) }
          .panel{ position:fixed; ${box} z-index:2147483001; display:flex; flex-direction:column;
                  padding:16px; box-sizing:border-box; overflow-y:auto;
                  background:${bg}; color:${fg} }
          .ptop{ display:flex; align-items:flex-start; gap:12px; width:100%;
                 padding-bottom:12px;
                 border-bottom:1px solid rgba(127,127,127,.25) }
          .ptitle{ flex:1; min-width:0 }
          .ptitle b{ display:block; font-size:14px; font-weight:600 }
          .ptitle span{ font-size:12px; opacity:.7 }
          .px{ border:0; background:none; color:inherit; font:inherit; font-size:18px;
               line-height:1; padding:6px; border-radius:8px; cursor:pointer; opacity:.6 }
          .px:hover{ opacity:1; background:rgba(127,127,127,.16) }
          .layers{ width:100%; padding-top:14px }
          /* Слой стола: подпись слева, плитки справа. Ширина колонки заголовка и
             размеры карточек взяты со стола Ядра — панель обязана выглядеть тем же
             местом, а не соседним. */
          .layer{ display:grid; grid-template-columns:116px minmax(0,1fr); gap:16px;
                  padding:14px 0; border-top:1px solid rgba(127,127,127,.25) }
          .layer:first-child{ border-top:0; padding-top:0 }
          .layer h4{ margin:6px 0 0; font-size:11px; font-weight:600; letter-spacing:.1em;
                     text-transform:uppercase; opacity:.6 }
          .layer h4 span{ display:block; margin-top:2px; font-size:11px; font-weight:400;
                          letter-spacing:0; text-transform:none; opacity:.75 }
          .grid{ display:grid; gap:8px; width:100%;
                 grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)) }
          .tile{ display:flex; flex-direction:column; gap:8px; padding:10px 12px; box-sizing:border-box;
                 border:1px solid rgba(127,127,127,.28); border-radius:12px;
                 background:rgba(127,127,127,.06); color:inherit; font:inherit; text-align:left;
                 cursor:pointer; transition:border-color .2s, background .2s }
          .tile:hover{ border-color:rgba(80,130,255,.5); background:rgba(127,127,127,.14) }
          .tile .row{ display:flex; align-items:center; gap:10px; width:100% }
          .tile .ico{ flex:0 0 auto; display:inline-flex; padding:6px; border-radius:8px;
                      background:rgba(80,130,255,.14); color:#5b8cff }
          .tile:hover .ico{ background:#3b7bff; color:#fff }
          .tile .ico svg{ width:16px; height:16px }
          .tile .nm{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
                     font-size:14px; font-weight:500 }
          .tile .ext{ flex:0 0 auto; opacity:.55 }
          .tile .ext svg{ width:14px; height:14px }
          .tile .dot{ flex:0 0 auto; width:8px; height:8px; border-radius:50% }
          .tile .desc{ font-size:11px; line-height:1.35; opacity:.7;
                       border-top:1px solid rgba(127,127,127,.2); padding-top:7px;
                       display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
                       overflow:hidden }
          .spin{ animation:eco-spin 1s linear infinite; display:inline-flex }
          @keyframes eco-spin{ to{ transform:rotate(360deg) } }
        </style>
        ${showPages && !collapsed && showApps ? `<div class="head">${escapeHtml(label)}</div>` : ''}
        ${showApps ? `
          <button class="nav ${collapsed ? 'narrow' : ''}" id="apps" aria-expanded="${this.#open}"
                  title="Приложения пространства">
            ${this.#busy ? `<span class="spin">${svg(ICONS.apps)}</span>` : svg(ICONS.apps)}
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
          <div class="scrim" data-close></div>
          <section class="panel" role="dialog" aria-label="Приложения пространства">
            <div class="ptop">
              <div class="ptitle">
                <b>Приложения пространства</b>
                <span>Выберите, куда перейти - экран под панелью останется на месте</span>
              </div>
              <button class="px" data-close title="Закрыть">✕</button>
            </div>
            <div class="layers">
              ${this.#apps === null ? '' : layersOf(this.#apps).map((group) => `
                <div class="layer">
                  <h4>${escapeHtml(group.title)}${group.hint ? `<span>${escapeHtml(group.hint)}</span>` : ''}</h4>
                  <div class="grid">
                    ${group.items.map((a) => {
                      const state = readinessOf(a.code)
                      const hint = [a.name || a.code, a.description,
                        a.mode === 'link' ? 'вход отдельный' : '',
                        state ? READINESS_LABEL[state] : ''].filter(Boolean).join(' · ')
                      return `
                      <button class="tile" data-app="${escapeHtml(a.code)}" title="${escapeHtml(hint)}">
                        <span class="row">
                          <span class="ico">${this.#busy === a.code
                            ? `<span class="spin">${svg(ICONS.apps)}</span>`
                            : svg(PRODUCT_ICONS[a.icon] || PRODUCT_ICONS['layout-grid'])}</span>
                          <span class="nm">${escapeHtml(a.name || a.code)}</span>
                          ${a.mode === 'link' ? `<span class="ext">${svg(ICONS.external)}</span>` : ''}
                          ${state ? `<span class="dot" style="background:${DOT_COLOR[state]}"></span>` : ''}
                        </span>
                        ${a.description ? `<span class="desc">${escapeHtml(a.description)}</span>` : ''}
                      </button>`
                    }).join('')}
                  </div>
                </div>`).join('')}
            </div>
            ${this.#apps === null ? '<div class="head">Загрузка…</div>' : ''}
          </section>` : ''}
      `

      const appsBtn = root.getElementById('apps')
      if (appsBtn) appsBtn.onclick = () => { this.#open = !this.#open; this.render() }
      root.querySelectorAll('[data-close]').forEach((el) => { el.onclick = () => this.#close() })
      const deskTile = root.querySelector('[data-home]')
      if (deskTile) deskTile.onclick = (e) => {
        if (wantsNewTab(e)) window.open(home, '_blank', 'noopener,noreferrer')
        else location.assign(home)
      }
      root.querySelectorAll('[data-app]').forEach((el) => {
        const app = (this.#apps || []).find((a) => a.code === el.dataset.app)
        if (!app) return
        const busy = (code) => { this.#busy = code; this.render() }
        el.onclick = (e) => { if (!this.#busy) openApp(app, wantsNewTab(e), busy) }
        el.onauxclick = (e) => { if (e.button === 1 && !this.#busy) openApp(app, true, busy) }
      })
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
