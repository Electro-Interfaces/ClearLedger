import { CalendarClock, Lock, Unlock, AlertTriangle } from 'lucide-react'

const demoPeriods = [
  { period: 'Январь 2026', status: 'closed' as const },
  { period: 'Февраль 2026', status: 'closed' as const },
  { period: 'Март 2026', status: 'closed' as const },
  { period: 'Апрель 2026', status: 'open' as const },
]

export function PeriodsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Периоды</h1>
        <p className="text-muted-foreground mt-1">
          Управление учётными периодами: открытые и закрытые
        </p>
      </div>

      <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-4">
        <p className="text-sm text-yellow-600 dark:text-yellow-400">
          Подключение к 1С не настроено. Данные периодов отображаются как пример.
        </p>
      </div>

      <div className="rounded-lg border bg-card">
        <div className="p-4 border-b">
          <h3 className="font-medium flex items-center gap-2">
            <CalendarClock className="h-4 w-4" />
            Учётные периоды
          </h3>
        </div>

        <div className="divide-y">
          {demoPeriods.map((p) => (
            <div key={p.period} className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-3">
                {p.status === 'closed' ? (
                  <Lock className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <Unlock className="h-4 w-4 text-green-500" />
                )}
                <span className="text-sm font-medium">{p.period}</span>
              </div>
              <div className="flex items-center gap-2">
                {p.status === 'closed' ? (
                  <span className="inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                    Закрыт
                  </span>
                ) : (
                  <span className="inline-flex items-center rounded-full bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-600 dark:text-green-400">
                    Открыт
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border bg-card p-5 space-y-3">
        <h3 className="font-medium flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-yellow-500" />
          Правила работы с периодами
        </h3>
        <ul className="space-y-1.5 text-sm text-muted-foreground">
          <li>Открытый период — свободная корректировка документов</li>
          <li>Закрытый период — корректировка только с разрешения и аудитом</li>
          <li>При загрузке первичных документов — обязательная сверка с 1С по закрытым периодам</li>
          <li>Корректировочные документы по закрытым периодам создаются в текущем открытом периоде</li>
        </ul>
      </div>
    </div>
  )
}
