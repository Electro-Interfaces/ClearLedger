import { Link } from 'react-router-dom'
import { formatDate } from '@/lib/formatDate'
import type { TechConnectionView } from '@/services/techConnectionView'

export function TechConnectionSummary({ view, siteId }: { view: TechConnectionView; siteId: string }) {
  const url = `/projects?mode=projects&sub=pr_project&project=${siteId}&ptab=tp`
  const handover = view.handover
  return <section className="space-y-3 border-y py-4" aria-label="Присоединение и электроснабжение">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="font-medium">Присоединение и электроснабжение</h3>
      <Link className="text-sm text-primary underline underline-offset-4" to={url}>Открыть присоединение</Link></div>
    <p className="text-sm text-muted-foreground">{view.scenario}{!view.enabled && ' · методика не включена'}</p>
    {!view.branches.length && <p className="text-sm">Выберите способ подключения и снабжения в карточке присоединения.</p>}
    <ul className="space-y-2">{view.branches.map((branch) => <li key={branch.key} className="text-sm">
      <span className="font-medium">{branch.label}: </span>{branch.stage.name || (view.enabled ? 'ожидается сверка процесса' : 'учёт по подтверждённым датам')}
      {branch.performer?.name && <span className="text-muted-foreground"> · {branch.performer.name}</span>}
      {branch.due && <span className={branch.overdue ? 'text-destructive' : 'text-muted-foreground'}> · срок {formatDate(branch.due)}</span>}
    </li>)}</ul>
    {view.kit && view.kit.required > 0 && <p className="text-sm">Документы заявки: {view.kit.present} из {view.kit.required}, проверено {view.kit.checked}.{view.kit.ready ? ' Комплект готов к подаче.' : ' Проверьте недостающие сведения и содержание файлов.'}</p>}
    {(view.stagesTotal > 0 || view.openRemarks > 0) && <p className="text-sm text-muted-foreground">Этапы ТУ приняты: {view.stagesAccepted} из {view.stagesTotal}. Открытых замечаний: {view.openRemarks}.</p>}
    {!!view.deadlines.length && <div className="text-sm text-destructive" role="status"><p>Просрочено по методике: {view.deadlines.length}</p>
      <ul className="mt-1 space-y-1">{view.deadlines.slice(0, 3).map((item) => <li key={item.key}>{item.label} · {formatDate(item.due)}</li>)}</ul></div>}
    {handover?.exists && <p className="text-sm"><Link className="text-primary underline underline-offset-4" to={`/docs/work?doc=${handover.docId}`}>Итоговый комплект</Link> · {handover.done ? 'все контролирующие ознакомлены' : `ожидается ознакомление: ${handover.recipients.filter((r) => r.status !== 'done').length} из ${handover.recipients.length}`}</p>}
    {view.error && <p role="status" className="text-sm text-amber-700 dark:text-amber-300">Состояние процесса не обновилось. Откройте присоединение и проверьте сообщение о связи.</p>}
    {view.syncedAt && <p className="text-xs text-muted-foreground">Сверено {new Date(view.syncedAt).toLocaleString('ru-RU')}</p>}
  </section>
}

/** Короткое состояние ТП остаётся доступным из любой вкладки проекта. */
export function TechConnectionStatus({ view, fallback, onOpen }: { view?: TechConnectionView; fallback?: string; onOpen: () => void }) {
  return <div className="flex flex-wrap gap-2 text-xs" aria-label="Ход присоединения проекта">
    {!view?.branches.length ? <button type="button" className="rounded border px-2 py-1 text-left hover:bg-muted" onClick={onOpen}>ТП: {fallback || 'параметры не заданы'}</button>
      : view.branches.map((branch) => <button key={branch.key} type="button" className="rounded border px-2 py-1 text-left hover:bg-muted" onClick={onOpen}>
        {branch.key === 'tp_supply' ? 'Сбыт' : 'ТП'}: {branch.stage.name || (!view.enabled ? (branch.key === 'tp_connection' ? fallback || 'по датам карточки' : 'методика не включена') : 'ожидается сверка')}
        {branch.performer?.name && <span className="text-muted-foreground"> · {branch.performer.name}</span>}
        {branch.due && <span className={branch.overdue ? 'text-destructive' : 'text-muted-foreground'}> · {formatDate(branch.due)}</span>}
      </button>)}
    {view?.error && <span className="self-center text-amber-700 dark:text-amber-300">Проверьте связь процесса в «Присоединении»</span>}
  </div>
}
