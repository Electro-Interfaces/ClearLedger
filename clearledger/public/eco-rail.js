/**
 * <eco-rail> — экосистемный рельс контейнера для приложений ВНЕ Ledger.
 *
 * Ядро отдаёт этот файл по адресу `/eco/rail.js` (nginx стека), приложение подключает
 * одной строкой и получает тот же правый край, что и в Ledger: выход на рабочий стол
 * и переход в Центр управления. Реализация одна на все приложения — ванильный
 * web-component, без React и без сборки, поэтому годится и для чужих фронтов.
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
 * Рельс перекрывал бы контент, поэтому при подключении добавляется отступ справа
 * на <html>; при удалении элемента отступ снимается.
 */
;(() => {
  if (customElements.get('eco-rail')) return

  const RAIL_W = 48
  const STYLE_ID = 'eco-rail-page-offset'

  // Иконки — контуры lucide (тот же язык, что в Ledger), currentColor.
  const ICONS = {
    home: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  }

  const svg = (paths) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`

  function ensurePageOffset() {
    if (document.getElementById(STYLE_ID)) return
    const s = document.createElement('style')
    s.id = STYLE_ID
    // Отступ на <html>: контент приложения не уезжает под рельс, а вёрстка внутри
    // остаётся его собственной — мы не трогаем ни body, ни его потомков.
    s.textContent = `html{padding-right:${RAIL_W}px;box-sizing:border-box}`
    document.head.appendChild(s)
  }

  function dropPageOffset() {
    document.getElementById(STYLE_ID)?.remove()
  }

  class EcoRail extends HTMLElement {
    static observedAttributes = ['admin', 'home', 'admin-url', 'label']

    connectedCallback() {
      ensurePageOffset()
      this.render()
    }

    disconnectedCallback() {
      if (!document.querySelector('eco-rail')) dropPageOffset()
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

      // Цвета намеренно нейтральные (полупрозрачный серый + currentColor): рельс
      // одинаково читается на светлой и тёмной теме любого приложения, не требуя
      // от него ни переменных, ни классов.
      root.innerHTML = `
        <style>
          :host{
            position:fixed; top:0; right:0; bottom:0; width:${RAIL_W}px; z-index:2147483000;
            display:flex; flex-direction:column; align-items:center; justify-content:flex-end;
            gap:4px; padding:8px 0; box-sizing:border-box;
            border-left:1px solid rgba(127,127,127,.28);
            background:rgba(127,127,127,.08); backdrop-filter:blur(6px);
            font:400 10px/1.2 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
          }
          a{
            display:flex; flex-direction:column; align-items:center; gap:2px;
            width:44px; padding:8px 2px; border-radius:8px; text-decoration:none;
            color:inherit; opacity:.72; transition:background .15s,opacity .15s;
          }
          a:hover{ background:rgba(127,127,127,.18); opacity:1 }
          svg{ width:16px; height:16px }
          span{ text-align:center }
        </style>
        <a href="${home}" title="Рабочий стол · ${label}">${svg(ICONS.home)}<span>Стол</span></a>
        ${showAdmin
          ? `<a href="${adminUrl}" title="Центр управления">${svg(ICONS.shield)}<span>Центр</span></a>`
          : ''}
      `
    }
  }

  customElements.define('eco-rail', EcoRail)
})()
