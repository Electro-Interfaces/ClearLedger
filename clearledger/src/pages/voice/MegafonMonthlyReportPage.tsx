import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Download, Printer, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCompany } from '@/contexts/CompanyContext'
import { getMegafonVoice } from '@/services/megafonVoiceService'
import { скачатьCSV, скачатьExcel } from './exportTable'
import { currentMonth, monthlyBounds, monthlyDate, monthlyLimits, monthlyMetrics, monthlyPrint, monthlySheets, monthlyTitle, shiftMonth } from './megafonMonthly'

export default function MegafonMonthlyReportPage() {
  const { companyId } = useCompany()
  const [url, setUrl] = useSearchParams()
  const month = url.get('month') ?? currentMonth()
  const bounds = monthlyBounds(month)
  const changedCompany = url.has('voice_company') && url.get('voice_company') !== companyId
  const line = changedCompany ? '' : url.get('line') ?? ''
  const query = useQuery({
    queryKey: ['voice-megafon-monthly', companyId, month, line],
    queryFn: () => getMegafonVoice(companyId, { ...bounds!, line: line || undefined, page: 1, page_size: 1 }),
    enabled: !!companyId && !!bounds && !changedCompany, retry: false,
  })
  useEffect(() => {
    if (!companyId || (url.get('voice_company') === companyId && url.get('source') === 'megafon')) return
    const next = new URLSearchParams(url); next.set('voice_company', companyId); next.set('source', 'megafon')
    if (changedCompany) next.delete('line')
    setUrl(next, { replace: true })
  }, [url, setUrl, companyId, changedCompany])
  const data = !changedCompany && !query.isError ? query.data : undefined
  const generatedAt = query.dataUpdatedAt ? new Date(query.dataUpdatedAt).toISOString() : ''
  const sheets = data ? monthlySheets(data, month, line, generatedAt) : []
  const ready = !!data && !query.isFetching
  function change(key: string, value: string) {
    setUrl(previous => { const next = new URLSearchParams(previous); if (value) next.set(key, value); else next.delete(key); return next })
  }
  async function download(format: 'csv' | 'xlsx') {
    if (!ready) return
    try { const name = `мегафон-отчёт-${month}`; if (format === 'csv') скачатьCSV(name, sheets); else await скачатьExcel(name, sheets) }
    catch { toast.error('Не удалось подготовить файл отчёта') }
  }
  function print() {
    if (!ready) return
    const popup = window.open('', '_blank')
    if (!popup) { toast.error('Разрешите открытие печатной формы в браузере'); return }
    popup.opener = null; popup.document.open(); popup.document.write(monthlyPrint(sheets, month)); popup.document.close()
  }
  const integer = (value: number | null) => value == null ? '—' : value.toLocaleString('ru-RU')
  const options = data?.filters.lines ?? []
  const knownGroups = data?.groups.filter(g => g.name).reduce((sum, g) => sum + g.total, 0) ?? 0
  return <main aria-label="Месячный отчёт МегаФона" className="flex min-w-0 flex-col gap-4 p-3 md:p-5">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="font-headline text-lg font-semibold">Отчёт за месяц</h1><p className="text-sm text-muted-foreground">МегаФон ВАТС · сводка, операторы и группы · без номеров звонящих</p></div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={!ready} onClick={() => void download('csv')}><Download />CSV</Button>
        <Button variant="outline" size="sm" disabled={!ready} onClick={() => void download('xlsx')}><Download />Excel</Button>
        <Button variant="outline" size="sm" disabled={!ready} onClick={print}><Printer />Печать / PDF</Button>
      </div>
    </header>
    <section aria-label="Параметры отчёта" className="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-3">
      <Button variant="outline" size="icon" aria-label="Месяц раньше" disabled={!bounds || month === '1970-01'} onClick={() => change('month', shiftMonth(month, -1))}><ChevronLeft /></Button>
      <label className="flex items-center gap-2 text-sm">Месяц<Input aria-label="Месяц" className="w-44" type="month" min="1970-01" max={currentMonth()} value={bounds ? month : ''} onChange={event => change('month', event.target.value)} /></label>
      <Button variant="outline" size="icon" aria-label="Месяц позже" disabled={!bounds || month >= currentMonth()} onClick={() => change('month', shiftMonth(month, 1))}><ChevronRight /></Button>
      <label className="flex min-w-0 max-w-full flex-wrap items-center gap-2 text-sm">Линия<select aria-label="Линия отчёта" value={line} onChange={event => change('line', event.target.value)} className="min-h-9 min-w-0 max-w-full rounded-md border border-input bg-card px-2 text-sm sm:max-w-80"><option value="">Все линии</option>{line && !options.some(o => o.number === line) ? <option value={line}>{line}</option> : null}{options.map(o => <option key={o.key} value={o.number}>{o.name} · {o.number}</option>)}</select></label>
      <Button variant="outline" size="sm" disabled={!bounds || query.isFetching || !companyId} onClick={() => void query.refetch()}><RefreshCw />Обновить</Button>
    </section>
    {!bounds ? <p role="alert">Выберите корректный месяц не позже текущего. <Button variant="outline" size="sm" onClick={() => change('month', currentMonth())}>Текущий месяц</Button></p> : null}
    {query.isLoading ? <p role="status">Рассчитываем отчёт по истории МегаФона…</p> : null}
    {query.isError ? <div role="alert"><p>Не удалось рассчитать отчёт: {query.error instanceof Error ? query.error.message : 'Ошибка источника'}</p><Button variant="outline" onClick={() => void query.refetch()}>Повторить</Button></div> : null}
    {data && bounds ? <>
      <section className="flex flex-col gap-2 rounded-lg border bg-card p-4" aria-label="Состояние отчёта">
        <h2 className="font-semibold">{monthlyTitle(month)}</h2>
        <p className="text-sm">{month === currentMonth() ? 'Месяц продолжается. Данные по загруженной истории на момент синхронизации.' : 'Рассчитан по загруженной истории. Поздние обновления могут изменить результат.'}</p>
        <p className="text-xs text-muted-foreground">Часовой пояс: {Intl.DateTimeFormat().resolvedOptions().timeZone}. Период: {monthlyDate(bounds.from)} — {monthlyDate(bounds.to)}, конец не включён. Синхронизация: {monthlyDate(data.connection.last_sync_at)}. Сформирован: {monthlyDate(generatedAt)}.</p>
        {!data.connection.configured ? <p role="note" className="text-sm">Подключение МегаФона для компании не настроено.</p> : null}
        {data.connection.last_error ? <p role="alert" className="text-sm">{data.connection.last_error}</p> : null}
        {data.summary.total === 0 ? <p role="note" className="text-sm">В загруженной истории за выбранный месяц и линию звонков нет. Проверьте период и полноту загрузки.</p> : null}
        <Link className="text-sm text-primary underline" to={`/voice/calls?${new URLSearchParams({ source: 'megafon', from: bounds.from, to: bounds.to, ...(line ? { line } : {}) })}`}>Открыть звонки этого отчёта</Link>
      </section>
      <section aria-label="Показатели отчёта" className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-4">{monthlyMetrics(data).map(([label, value, formula]) => <div key={label} className="flex min-w-0 flex-col gap-1 rounded-lg border bg-card p-3"><span className="text-xs text-muted-foreground">{label}</span><strong className="text-xl">{integer(value)}</strong><span className="text-xs text-muted-foreground">{formula}</span></div>)}</section>
      <section className="flex min-w-0 flex-col gap-2" aria-label="Разрезы месячного отчёта">{sheets.slice(1, 3).map(sheet => <div key={sheet.имя} className="flex min-w-0 flex-col gap-2"><h2 className="font-semibold">{sheet.имя}</h2>{sheet.имя === 'Группы' ? <p role="note" className="text-sm text-muted-foreground">Группа указана для {integer(knownGroups)} из {integer(data.summary.total)} звонков. Полную нагрузку смен эти данные не описывают.</p> : null}<div className="min-w-0 overflow-x-auto rounded-lg border"><table aria-label={`${sheet.имя} за месяц`} className="w-full text-sm"><thead><tr>{sheet.строки[sheet.имя === 'Группы' ? 1 : 0].map((v, i) => <th key={i} className="whitespace-nowrap border-b bg-card p-2 text-left font-medium">{v}</th>)}</tr></thead><tbody>{sheet.строки.slice(sheet.имя === 'Группы' ? 2 : 1).map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j} className="border-b p-2">{v ?? '—'}</td>)}</tr>)}</tbody></table></div></div>)}</section>
      <section aria-label="Ограничения отчёта" className="flex flex-col gap-2 rounded-lg border bg-card p-4"><h2 className="font-semibold">Полнота данных</h2><ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-muted-foreground">{monthlyLimits.map(text => <li key={text}>{text}</li>)}</ul></section>
    </> : null}
  </main>
}
