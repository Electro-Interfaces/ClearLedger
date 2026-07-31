/**
 * Сетка прав по продуктам пространства: продукт целиком или его отдельные разделы.
 *
 * Дерево — общее с матрицей ролей (`useAccessTree`): каталог подключённых компании
 * продуктов + их разделы из карты меню. Отметка продукта покрывает все его разделы
 * (`app_allowed` на сервере), поэтому разделы отмеченного продукта блокируются.
 *
 * Используется в трёх местах: конструктор роли, доступ сотрудника, доступ участника
 * компании-партнёра — правила отметок одни и те же, поэтому и компонент один.
 */
import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { useAccessTree } from '@/hooks/useAccessTree'
import { appIcon } from '@/config/appIcons'

export function AccessTreeGrid({ companyId, sel, onToggle, onCarve, disabled, wide }: {
  companyId: string
  sel: Set<string>
  onToggle: (k: string) => void
  /** Клик по разделу продукта, включённого целиком: продукт «разжимается» — остаются
   *  все его разделы, кроме кликнутого. Раньше такие разделы были молча заблокированы,
   *  и чтобы закрыть человеку один пункт, надо было снять продукт и накликать
   *  остальные руками. Без колбэка — прежнее поведение (разделы недоступны). */
  onCarve?: (app: string, keep: string[]) => void
  disabled?: boolean
  /** Широкая раскладка в две колонки — для разворота прямо в строке списка. */
  wide?: boolean
}) {
  const { tree, isLoading } = useAccessTree(companyId)
  const [open, setOpen] = useState<Record<string, boolean>>({})

  return (
    <div className={`${wide ? 'grid gap-x-6 gap-y-1 md:grid-cols-2' : 'space-y-2 max-h-80 overflow-y-auto pr-1'} ${
      disabled ? 'opacity-40 pointer-events-none' : ''
    }`}>
      {isLoading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Загрузка каталога…
        </div>
      )}
      {tree.map((app) => {
        const appOn = sel.has(app.app)
        const picked = app.groups.flatMap((g) => g.modules).filter((m) => sel.has(m.key)).length
        const expanded = !!open[app.app]
        const Icon = appIcon(app.icon)
        return (
          <div key={app.app} className={wide ? 'break-inside-avoid' : undefined}>
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => setOpen((o) => ({ ...o, [app.app]: !o[app.app] }))}
                disabled={!app.count} className="p-1 text-muted-foreground disabled:opacity-0">
                {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              </button>
              <button type="button" onClick={() => onToggle(app.app)}
                className={`flex-1 flex items-center justify-between px-2.5 py-1.5 rounded-md text-sm text-left border font-medium transition-colors ${
                  appOn ? 'bg-primary/10 border-primary/40 text-foreground' : 'border-border hover:bg-accent/40'
                }`}>
                <span className="flex items-center gap-1.5">
                  <Icon className={`h-3.5 w-3.5 ${appOn ? 'text-primary' : 'text-muted-foreground'}`} />
                  {app.name}
                  <span className="text-[11px] text-muted-foreground/70">
                    {appOn ? '· весь продукт' : picked ? `· выбрано: ${picked}` : app.count ? `· разделов: ${app.count}` : ''}
                  </span>
                </span>
                {appOn && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
              </button>
            </div>
            {/* Разделы продукта, включённого целиком, — не «полупрозрачный шум»,
                а полноценные строки: включены все, и это сказано словами. */}
            {expanded && appOn && (
              <p className="ml-6 mt-1 px-1 text-[11px] text-muted-foreground">
                {onCarve
                  ? 'Продукт открыт целиком — включены все разделы. Клик по разделу закроет его, доступ станет по разделам.'
                  : 'Продукт открыт целиком — включены все разделы. Чтобы выбирать по одному, снимите отметку с продукта.'}
              </p>
            )}
            {expanded && app.groups.map((g) => (
              <div key={g.name} className="ml-6 mt-1 border-l pl-2">
                <div className="px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">{g.name}</div>
                <div className="flex flex-col gap-1">
                  {g.modules.map((m) => {
                    const on = appOn || sel.has(m.key)
                    return (
                      <button key={m.key} type="button" disabled={appOn && !onCarve}
                        onClick={() => appOn && onCarve
                          ? onCarve(app.app, app.groups.flatMap((gr) => gr.modules)
                              .map((x) => x.key).filter((k) => k !== m.key))
                          : onToggle(m.key)}
                        title={appOn && onCarve
                          ? `${m.name} включён со всем продуктом. Нажмите, чтобы закрыть этот раздел`
                          : undefined}
                        className={`flex items-center justify-between px-2.5 py-1 rounded-md text-[13px] text-left border transition-colors ${
                          on ? 'bg-primary/10 border-primary/40 text-foreground' : 'border-border text-muted-foreground hover:bg-accent/40'
                        }`}>
                        <span>{m.name}</span>
                        {on && <Check className={`h-3.5 w-3.5 shrink-0 ${appOn ? 'text-primary/60' : 'text-primary'}`} />}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
