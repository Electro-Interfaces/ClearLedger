/**
 * Переключатель видов рабочей области пункта меню (внутренние табы панели).
 *
 * Единый компонент для всех панелей (Сессии, Реализации, Розница, Тарифы,
 * Корпоратив…) — раньше разметка underline-табов копировалась в 8 файлов и
 * расходилась. Вид сегментированный: плашка-контейнер с «поднятым» активным
 * сегментом читается как переключатель, а не как набор ссылок.
 */

export interface ViewTab {
  k: string
  label: string
}

export function PanelViewTabs({
  tabs,
  value,
  onChange,
  label = 'Вид',
  ariaLabel = 'Виды раздела',
}: {
  tabs: readonly ViewTab[]
  value: string
  onChange: (key: string) => void
  /** Подпись слева; null — без подписи (когда рядом уже есть контекстный бейдж). */
  label?: string | null
  ariaLabel?: string
}) {
  return (
    <div data-zone="Вид раздела" className="flex min-w-0 items-center gap-2 py-2">
      {label ? (
        <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
      ) : null}

      <div
        role="tablist"
        aria-label={ariaLabel}
        className="flex min-w-0 items-center gap-0.5 overflow-x-auto rounded-lg border border-border bg-muted/60 p-1 scrollbar-hide"
      >
        {tabs.map((t) => {
          const on = t.k === value
          return (
            <button
              key={t.k}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => onChange(t.k)}
              // На мобиле цель пальца: 28 px по высоте — промах через раз.
              // Ниже sm поднимаем до 40 px, на десктопе компактность сохраняем.
              className={`min-h-10 whitespace-nowrap rounded-md px-3.5 py-2 text-[13px] transition-colors sm:min-h-0 ${
                on
                  ? 'bg-primary font-semibold text-primary-foreground shadow-soft'
                  : 'text-muted-foreground hover:bg-card/70 hover:text-foreground'
              }`}
            >
              {t.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
