/**
 * «План работ по парку» — переносы, модернизации и демонтажи по регионам.
 *
 * Ось экрана — РАБОТА, а не объект: в реестре проектов строка отвечает на «что у нас
 * есть», здесь — на «что, где, когда и кем делаем». Поэтому это отдельный пункт меню,
 * а не сохранённый фильтр реестра.
 *
 * Раскладка повторяет рабочий файл заказчика (реестр Титова): группировка по региону,
 * внутри — объект, вид работы, стадия, ответственный, плановая дата. Первую стройку
 * (`new_build`) сюда не берём: она ведётся проектом с нуля и живёт в воронке.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Loader2, CalendarClock, Upload, MessageSquarePlus } from 'lucide-react'
import {
  getProjects, importParkPlanXlsx, STAGE_META,
  type ParkPlanImportReport, type ProjectRow, type SiteStage,
} from '@/services/sitesService'
import { SiteCardDialog } from './SiteCardDialog'
import { useOpenProject } from './useOpenProject'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

// Виды работ парка. Первая стройка — не работа по парку, её здесь нет.
const PARK_KINDS = 'relocation,retrofit,decommission'

const NO_REGION = 'Регион не указан'

function regionOf(p: ProjectRow): string {
  return p.site?.region?.trim() || NO_REGION
}

function placeOf(p: ProjectRow): string {
  return p.location?.name || p.site?.address || p.title || '—'
}

export function ParkWorkPlanPanel({ companyId }: { companyId: string }) {
  const [detailId, setDetailId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [onlyOpen, setOnlyOpen] = useState(true)
  const openProject = useOpenProject()
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['pr-park-plan', companyId],
    queryFn: () => getProjects(companyId, { kind: PARK_KINDS }),
  })

  // Импорт рабочего реестра: сначала предпросмотр, запись — вторым нажатием.
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<ParkPlanImportReport | null>(null)
  const [pending, setPending] = useState<File | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const runImport = async (file: File, dryRun: boolean) => {
    setBusy(true); setErr(null)
    try {
      const r = await importParkPlanXlsx(companyId, file, dryRun)
      setReport(r); setPending(dryRun ? file : null)
      if (!dryRun) await qc.invalidateQueries({ queryKey: ['pr-park-plan', companyId] })
    } catch (e) {
      setErr(e instanceof Error
        ? `Файл не разобрали: ${e.message}. Проверьте, что это реестр работ по парку, а не банк данных ЗУ.`
        : 'Файл не разобрали — проверьте, что это реестр работ по парку')
    } finally {
      setBusy(false)
      if (dryRun && fileRef.current) fileRef.current.value = ''
    }
  }

  const today = new Date().toISOString().slice(0, 10)

  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const rows = (q.data ?? []).filter((p) => {
      if (onlyOpen && (p.stage === 'archive' || p.closedOn)) return false
      if (!needle) return true
      return [p.projectNo, p.title, placeOf(p), regionOf(p), p.ownerName]
        .some((v) => (v ?? '').toLowerCase().includes(needle))
    })
    const byRegion = new Map<string, ProjectRow[]>()
    for (const p of rows) {
      const key = regionOf(p)
      const list = byRegion.get(key)
      if (list) list.push(p); else byRegion.set(key, [p])
    }
    // Регион без названия — в конец: это дырка в данных, а не полноценная группа.
    return [...byRegion.entries()]
      .map(([region, items]) => ({
        region,
        items: items.sort((a, b) =>
          (a.nextActionDue ?? '9999').localeCompare(b.nextActionDue ?? '9999')),
        overdue: items.filter((p) => p.nextActionDue && p.nextActionDue < today).length,
      }))
      .sort((a, b) => (a.region === NO_REGION ? 1 : b.region === NO_REGION ? -1
        : a.region.localeCompare(b.region, 'ru')))
  }, [q.data, search, onlyOpen, today])

  if (q.isLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  const total = groups.reduce((a, g) => a + g.items.length, 0)
  const overdue = groups.reduce((a, g) => a + g.overdue, 0)

  return (
    <div className="p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div data-zone="План работ по парку">
          <h2 className="text-base font-semibold">План работ по парку</h2>
          <p className="text-sm text-muted-foreground">
            Переносы, модернизации и демонтажи по регионам: {nf0.format(total)} работ
            {overdue > 0 && <>, из них просрочено <span className="text-red-600 dark:text-red-400">{nf0.format(overdue)}</span></>}.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <Input className="h-10 sm:h-8 w-full sm:w-[240px] text-sm" value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Регион, объект, номер, ответственный" />
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />
            только в работе
          </label>
          <input ref={fileRef} type="file" accept=".xlsx,.xls" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) runImport(f, true) }} />
          <Button variant="outline" size="sm" className="h-10 sm:h-8 text-sm" disabled={busy}
            onClick={() => fileRef.current?.click()}>
            {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Upload className="h-3.5 w-3.5 mr-1" />}
            Импорт реестра работ (xlsx)
          </Button>
        </div>
      </div>

      {err && (
        <div className="rounded-lg border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 px-3 py-2 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}
      {report && (
        <ImportReport report={report} busy={busy}
          onConfirm={pending ? () => runImport(pending, false) : undefined} />
      )}

      {/* Три разных «пусто» — три разных ответа. Отказ запроса, отфильтрованная
          выдача и настоящее отсутствие работ выглядели одинаково: «работ нет».
          Первое — неправда, второе отправляет искать данные, которые на месте. */}
      {q.isError ? (
        <Card><CardContent className="py-10 text-center text-sm space-y-2">
          <div>План работ не загрузился: {q.error instanceof Error ? q.error.message : 'нет связи с сервером'}</div>
          <Button size="sm" variant="outline" onClick={() => q.refetch()}>Повторить</Button>
        </CardContent></Card>
      ) : total === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          {(q.data?.length ?? 0) > 0
            ? 'Ничего не найдено по заданным условиям — измените поиск или снимите «только в работе».'
            : 'Работ по парку нет. Перенос, модернизацию или демонтаж заводят в карточке объекта — блок «Работы на объекте».'}
        </CardContent></Card>
      ) : groups.map((g) => (
        <Card key={g.region}>
          <CardContent className="p-0">
            <div className="px-3 py-2 border-b bg-muted/40 flex items-center gap-2">
              <span className="text-sm font-semibold">{g.region}</span>
              {g.overdue > 0 && (
                <span className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1">
                  <CalendarClock className="h-3.5 w-3.5" />просрочено {g.overdue}
                </span>
              )}
              <span className="font-mono text-sm text-muted-foreground ml-auto">{nf0.format(g.items.length)}</span>
            </div>
            {/* Телефон: та же строка без прокрутки вбок. */}
            <ul className="sm:hidden divide-y divide-border/40">
              {g.items.map((p) => {
                const late = !!p.nextActionDue && p.nextActionDue < today
                return (
                  <li key={p.id}>
                    <button type="button" onClick={() => openProject(p.siteId)}
                      className="w-full text-left px-3 py-3 active:bg-muted/40">
                      <div className="flex items-baseline gap-2">
                        <span className="font-mono text-xs text-muted-foreground">{p.projectNo ?? '—'}</span>
                        <span className="text-[11px] rounded border px-1.5 py-0.5">{p.kindLabel}</span>
                      </div>
                      <div className="mt-1 text-sm">{placeOf(p)}</div>
                      <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                        <span>{p.ownerName ?? 'не назначен'}</span>
                        {p.nextActionDue && (
                          <span className={late ? 'text-red-600 dark:text-red-400' : ''}>до {p.nextActionDue}</span>
                        )}
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
            <table className="hidden sm:table w-full text-sm">
              {/* Семь колонок без шапки читаются как набор обрывков: «Лид» — это
                  стадия объекта или ход работы? Называем каждую, иначе строку
                  нельзя ни понять, ни оспорить. */}
              <thead>
                <tr className="text-xs text-muted-foreground border-b border-border/60">
                  <th className="p-2 text-left font-normal">Проект</th>
                  <th className="p-2 text-left font-normal">Место</th>
                  <th className="p-2 text-left font-normal">Вид работы</th>
                  <th className="p-2 text-left font-normal">Стадия проекта</th>
                  <th className="p-2 text-left font-normal">Ответственный</th>
                  <th className="p-2 text-left font-normal">Следующий шаг</th>
                  <th className="p-2 text-left font-normal">Срок</th>
                </tr>
              </thead>
              <tbody>
                {g.items.map((p) => {
                  const late = !!p.nextActionDue && p.nextActionDue < today
                  return (
                    // Строка — не только для мыши: с клавиатуры проект иначе не открыть.
                    <tr key={p.id} className="border-b border-border/30 hover:bg-muted/30 cursor-pointer
                        focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                      tabIndex={0} role="link"
                      onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openProject(p.siteId) } }}
                      onClick={(ev) => (ev.altKey ? setDetailId(p.siteId) : openProject(p.siteId))}>
                      <td className="p-2 whitespace-nowrap font-mono w-32 text-muted-foreground">{p.projectNo ?? '—'}</td>
                      <td className="p-2 max-w-[320px] truncate">{placeOf(p)}</td>
                      <td className="p-2 w-36 whitespace-nowrap text-muted-foreground">{p.kindLabel}</td>
                      <td className="p-2 w-44">
                        <span className={`text-xs rounded border px-1.5 py-0.5 ${STAGE_META[p.stage as SiteStage]?.cls ?? ''}`}>
                          {p.stageLabel}
                        </span>
                      </td>
                      <td className="p-2 w-44 truncate text-muted-foreground">{p.ownerName ?? 'не назначен'}</td>
                      <td className="p-2 max-w-[260px] truncate text-muted-foreground">{p.nextAction ?? ''}</td>
                      <td className={`p-2 w-28 whitespace-nowrap font-mono ${late ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                        {p.nextActionDue ?? '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}

      {detailId && <SiteCardDialog companyId={companyId} id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}

/**
 * Отчёт импорта. Показывает не «сколько строк прочитано», а что появится в системе
 * и что осталось за бортом с причиной: строку, которую импорт молча выбросил,
 * менеджер не найдёт уже никогда.
 */
function ImportReport({ report, busy, onConfirm }: {
  report: ParkPlanImportReport; busy: boolean; onConfirm?: () => void
}) {
  const [details, setDetails] = useState(false)
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm space-y-2">
      <div className="font-medium text-foreground">
        {report.dryRun ? 'Предпросмотр импорта (данные пока не записаны)' : 'Импорт выполнен ✓'}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
        <span>новых работ: <b className="text-foreground">{nf0.format(report.created)}</b></span>
        <span>обновлено: <b className="text-foreground">{nf0.format(report.updated)}</b></span>
        <span>встало на объект сети: {nf0.format(report.linkedToObject)}</span>
        {report.toFunnel > 0 && <span>новых строек в воронку: {nf0.format(report.toFunnel)}</span>}
      </div>

      {report.tickets.length > 0 && (
        <div className="rounded border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-2.5 py-2 space-y-1">
          <div className="flex items-center gap-1.5 font-medium text-amber-900 dark:text-amber-200">
            <MessageSquarePlus className="h-3.5 w-3.5" />
            Лист «Ремонты»: {report.tickets.length} — это заявки, а не проекты
          </div>
          <p className="text-amber-800 dark:text-amber-300/90">
            Восстановление работоспособности (замена автомата в щите, ремонт узла) ведётся
            заявкой поддержки по объекту, а не капитальной работой. Импорт такие строки
            не заводит — заведите их кнопкой «Заявка в поддержку» в карточке объекта.
          </p>
          <ul className="text-amber-900/80 dark:text-amber-300/80 list-disc pl-4">
            {report.tickets.slice(0, 8).map((t) => (
              <li key={`${t.sheet}-${t.row}`}>{t.address}{t.comment && <> — {t.comment}</>}</li>
            ))}
          </ul>
        </div>
      )}

      {report.skipped.length > 0 && (
        <div>
          <button className="underline underline-offset-2 text-muted-foreground hover:text-foreground"
            onClick={() => setDetails((v) => !v)}>
            не взято строк: {report.skipped.length} — {details ? 'свернуть' : 'посмотреть почему'}
          </button>
          {details && (
            <ul className="mt-1 max-h-56 overflow-auto list-disc pl-4 text-muted-foreground">
              {report.skipped.map((s) => (
                <li key={`${s.sheet}-${s.row}`}>
                  <span className="font-mono text-xs">{s.sheet}:{s.row}</span> {s.address} — {s.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {report.unknownSheets.length > 0 && (
        <div className="text-muted-foreground">
          листы неизвестного вида (пропущены целиком): {report.unknownSheets.join(', ')}.
          Импорт читает листы: «Объекты все регионы», «Комплексные _ДВ», «ПИР», «Разобрать»,
          «Выполненные», «Закрытые работы», «Ремонты».
        </div>
      )}

      {onConfirm && (
        <Button size="sm" className="h-8 text-sm" disabled={busy} onClick={onConfirm}>
          {busy && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />}
          Записать в систему
        </Button>
      )}
    </div>
  )
}
