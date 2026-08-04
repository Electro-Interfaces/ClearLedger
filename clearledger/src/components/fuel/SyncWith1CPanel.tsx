/**
 * Раздел «Сверка» — наши факты против того, что проведено в БП ГИГ.
 *
 * Два фокуса одного экрана (пункты «Ledger ↔ 1С» и «Расхождения»): первый отвечает
 * «сошлось ли», второй — «что именно разошлось и куда идти чинить».
 *
 * Воронки пакетов draft→queued→sent→acked здесь больше нет (04.08.2026). Она
 * описывала доставку, которой не существует: очередь `/export-packets/queue`
 * реализована, но расширение TradeLedger.cfe к ней не обращается — топливо оно
 * тянет из STS напрямую, сопутка едет файлом пакета. Счётчики стояли на `draft`
 * вечно и читались как «ничего не загружено», хотя документы в БП были.
 *
 * Переиспользует: /fuel/readiness, /reconciliation/summary.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { format, subMonths } from 'date-fns'
import {
  ClipboardCheck, CheckCircle2, AlertTriangle, RefreshCw,
  GitCompare, ExternalLink, XCircle,
} from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { getFuelReadiness } from '@/services/fuel/fuelMappingService'
import {
  getReconciliationSummary, runReconciliation, getAccountingDocs,
} from '@/services/accountingDocService'
import { fmtMoney } from '@/services/analyticsService'
import { DOC_TYPE_LABELS } from '@/config/statuses'

const H3 = 'text-xs font-semibold uppercase tracking-wide text-muted-foreground'
const fmtN = (v: number) => (v ?? 0).toLocaleString('ru-RU')

/** Фокус экрана: сводка «сошлось ли» либо разбор того, что разошлось. */
export type ReconFocus = 'recon_docs' | 'recon_diff'

export function SyncWith1CPanel({ focus = 'recon_docs' }: { focus?: ReconFocus } = {}) {
  const { company } = useCompany()
  const companyId = company.id
  const qc = useQueryClient()
  const nav = useNavigate()
  const [running, setRunning] = useState(false)
  const [period, setPeriod] = useState<'month' | 'quarter'>('month')
  const from = format(subMonths(new Date(), period === 'month' ? 1 : 3), 'yyyy-MM-dd')
  const to = format(new Date(), 'yyyy-MM-dd')
  const api = isApiEnabled()

  const readiness = useQuery({ queryKey: ['fuel-readiness', companyId, from, to], queryFn: () => getFuelReadiness(from, to) })
  const recon = useQuery({ queryKey: ['reconciliation-summary', companyId], queryFn: () => getReconciliationSummary(companyId) })
  // Построчный разбор нужен только на «Расхождениях»: на сводке это лишний запрос
  // и лишняя таблица, которую всё равно никто не читает до вопроса «а что не так».
  const diffs = useQuery({
    queryKey: ['acc-docs', companyId, 'discrepancy', from, to],
    queryFn: () => getAccountingDocs(companyId, { matchStatus: 'discrepancy', dateFrom: from, dateTo: to }),
    enabled: focus === 'recon_diff',
  })

  const runRecon = async () => {
    setRunning(true)
    try {
      await runReconciliation(companyId)
      await qc.invalidateQueries({ queryKey: ['reconciliation-summary'] })
    } finally { setRunning(false) }
  }

  const rs = recon.data
  const noOneC = !rs || rs.totalAccDocs === 0
  const diffOnly = focus === 'recon_diff'

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">{diffOnly ? 'Расхождения' : 'Сверка Ledger ↔ 1С'}</h2>
        <span className="text-xs text-muted-foreground">
          {diffOnly
            ? 'что разошлось по суммам и что не нашло пары'
            : 'наши факты против проведённых документов БП ГИГ'}
        </span>
        <div className="ml-auto flex gap-1 rounded-lg bg-card p-1">
          {(['month', 'quarter'] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={cn('rounded px-3 py-1 text-xs transition-colors', period === p ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-accent/40')}>
              {p === 'month' ? 'Месяц' : 'Квартал'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Разница приложение ↔ 1С ── */}
      <Card>
        <CardContent className="pt-4">
          <div className="mb-3 flex items-center gap-2">
            <GitCompare className="h-4 w-4 text-primary" />
            <h3 className={H3}>Разница приложение ↔ 1С</h3>
            <Button size="sm" variant="outline" className="ml-auto h-7 gap-1 text-xs" onClick={runRecon} disabled={running || !api}>
              <RefreshCw className={cn('h-3 w-3', running && 'animate-spin')} /> Запустить сверку
            </Button>
          </div>
          {noOneC ? (
            <div className="flex items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-3 text-xs text-amber-700 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                Нет документов из 1С для сверки. Настройте подключение к 1С (Настройки → Интеграция с 1С)
                и синхронизируйте документы — тогда здесь появится построчная разница сумм и объёмов.
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Загружено в 1С (сматчено)" value={rs!.matched} cls="text-emerald-600 dark:text-emerald-400" icon={CheckCircle2} />
              <Stat label="Ещё не в 1С" value={rs!.unmatchedEntry} cls={rs!.unmatchedEntry > 0 ? 'text-amber-600 dark:text-amber-400' : ''} icon={rs!.unmatchedEntry > 0 ? AlertTriangle : undefined} />
              <Stat label="Расхождения сумм" value={rs!.discrepancy} cls={rs!.discrepancy > 0 ? 'text-red-500' : ''} icon={rs!.discrepancy > 0 ? XCircle : undefined} />
            </div>
          )}
          {!noOneC && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Наших записей (L2): {fmtN(rs!.totalEntries)}, из них сопоставлено с 1С: {fmtN(rs!.matched)}.
              Сверка по номеру, дате, ИНН и сумме (±1% — норма, свыше — расхождение).
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Построчный разбор: только на «Расхождениях» ── */}
      {diffOnly && !noOneC && (
        <Card>
          <CardContent className="pt-4">
            <div className="mb-3 flex items-center gap-2">
              <XCircle className="h-4 w-4 text-red-500" />
              <h3 className={H3}>Документы с расхождением сумм</h3>
              <span className="ml-auto text-[11px] text-muted-foreground">
                {diffs.data ? `${fmtN(diffs.data.length)} за период` : ''}
              </span>
            </div>
            {diffs.isLoading ? (
              <p className="py-4 text-sm text-muted-foreground">Загружаем разбор…</p>
            ) : (diffs.data?.length ?? 0) === 0 ? (
              <p className="py-4 text-sm text-muted-foreground">
                Расхождений за период нет — суммы наших фактов сошлись с документами БП.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-border/60 text-[11px] text-muted-foreground">
                      <th className="py-1.5 text-left font-medium">Дата</th>
                      <th className="py-1.5 text-left font-medium">Документ</th>
                      <th className="py-1.5 text-left font-medium">Контрагент</th>
                      <th className="py-1.5 text-right font-medium">Сумма 1С</th>
                      <th className="py-1.5 text-left font-medium">В чём разница</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diffs.data!.slice(0, 100).map((d) => (
                      <tr key={d.id} className="cursor-pointer border-b border-border/30 hover:bg-accent/40"
                        onClick={() => nav('/1c/documents')}>
                        <td className="py-1.5 tabular-nums">{d.date}</td>
                        <td className="py-1.5">
                          {DOC_TYPE_LABELS[d.docType] ?? d.docType}
                          <span className="ml-1 text-muted-foreground">№{d.number}</span>
                        </td>
                        <td className="max-w-[220px] truncate py-1.5">{d.counterpartyName}</td>
                        <td className="py-1.5 text-right tabular-nums">{fmtMoney(d.amount)}</td>
                        <td className="py-1.5 text-xs text-muted-foreground">
                          {d.discrepancySummary ?? 'расхождение свыше 1%'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(diffs.data?.length ?? 0) > 100 && (
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    Показаны первые 100 из {fmtN(diffs.data!.length)}; остальные — в реестре документов.
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Что разбирать: наши факты без пары и расхождения сумм ── */}
      {!noOneC && (
        <Card>
          <CardContent className="pt-4">
            <div className="mb-3 flex items-center gap-2"><ClipboardCheck className="h-4 w-4 text-primary" /><h3 className={H3}>Требует разбора</h3></div>
            <div className="grid gap-2 sm:grid-cols-3">
              <ActionRow
                label="Наших фактов без пары"
                value={rs!.unmatchedEntry}
                hint="не загружено в БП либо не найдено"
                onClick={() => nav('/1c/documents')}
                danger={false}
              />
              <ActionRow
                label="Документы 1С без оригинала"
                value={rs!.unmatchedAcc}
                hint="заведены в БП помимо нас"
                onClick={() => nav('/1c/documents')}
                danger={false}
              />
              <ActionRow
                label="Расхождения сумм"
                value={rs!.discrepancy}
                hint="отличие свыше 1%"
                onClick={() => nav('/1c/documents')}
                danger={rs!.discrepancy > 0}
              />
            </div>
            {readiness.data && readiness.data.receipts.pending > 0 && (
              <p className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
                <AlertTriangle className="h-3 w-3 shrink-0" />
                {fmtN(readiness.data.receipts.pending)} ТТН ещё не проверены — подтвердите приёмку в разделе «Нефтепродукты → Поступления».
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function Stat({ label, value, cls, icon: Icon }: { label: string; value: number; cls?: string; icon?: typeof AlertTriangle }) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="flex items-center gap-1 text-[11px] text-muted-foreground">{Icon && <Icon className={cn('h-3 w-3', cls)} />}{label}</div>
      <div className={cn('mt-1 text-xl font-bold tabular-nums', cls)}>{fmtN(value)}</div>
    </div>
  )
}

function ActionRow({ label, value, hint, onClick, danger }: {
  label: string; value: number; hint: string; onClick: () => void; danger: boolean
}) {
  return (
    <button onClick={onClick}
      className={cn('flex items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/40',
        danger ? 'border-red-400/40 bg-red-500/[0.04]' : 'border-border bg-background')}>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] text-muted-foreground">{label}</div>
        <div className={cn('text-xl font-bold tabular-nums', danger && value > 0 ? 'text-red-500' : 'text-foreground')}>{fmtN(value)}</div>
        <div className="text-[10px] text-muted-foreground">{hint}</div>
      </div>
      <ExternalLink className="h-4 w-4 shrink-0 text-muted-foreground/50" />
    </button>
  )
}
