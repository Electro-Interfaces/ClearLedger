/**
 * «Переоценка» центра — две подачи одного дела.
 *
 * «Изменить цены» — инструмент: отбор, правило, предпросмотр, применение.
 * «Реестр из ЦБ» — история: что переоценивала 1С, пока станции вела она.
 *
 * Раньше пункт показывал только вторую подачу, и это была витрина прошлого:
 * посмотреть, что уже случилось, можно, а сделать что-то с ценами — нет.
 * Инструмент стоит первым, потому что за этим сюда и приходят.
 */
import { useState } from 'react'
import { StoreRepricingPanel } from './StoreRepricingPanel'
import { StoreRevaluationPanel } from './StoreRevaluationPanel'

const ВКЛАДКИ = [
  { key: 'tool', label: 'Изменить цены' },
  { key: 'log', label: 'Реестр из ЦБ' },
] as const

export function StorePricingWorkPanel({ companyId, dateFrom, dateTo, stations }: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]
}) {
  const [вкладка, setВкладка] = useState<'tool' | 'log'>('tool')
  return (
    <div>
      <div className="px-4 md:px-6 pt-4">
        <div className="inline-flex rounded-md border border-border/50 overflow-hidden">
          {ВКЛАДКИ.map((в) => (
            <button key={в.key} onClick={() => setВкладка(в.key)}
              className={`px-3 py-1.5 text-xs transition-colors ${
                вкладка === в.key
                  ? 'bg-primary/15 text-primary font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent/40'}`}>
              {в.label}
            </button>
          ))}
        </div>
      </div>
      {вкладка === 'tool'
        ? <StoreRepricingPanel companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} stations={stations} />
        : <StoreRevaluationPanel companyId={companyId} dateFrom={dateFrom} dateTo={dateTo} stations={stations} />}
    </div>
  )
}
