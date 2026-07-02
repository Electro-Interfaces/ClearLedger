/**
 * Раздел «Сверка с 1С» — готовность к загрузке + разница приложение↔1С.
 * Секции: воронка загрузки (пакеты L2→L3→L4) · разница приложение↔1С (reconciliation
 * по AccountingDoc из 1С) · проблемы (отклонённые пакеты, расхождения) с переходами.
 * Переиспользует: /fuel/readiness, /export-packets/stats, /reconciliation/summary.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { format, subMonths } from 'date-fns'
import {
  ClipboardCheck, Upload, CheckCircle2, AlertTriangle, RefreshCw,
  ArrowRight, GitCompare, ExternalLink, XCircle,
} from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useCompany } from '@/contexts/CompanyContext'
import { get, isApiEnabled } from '@/services/apiClient'
import { getFuelReadiness } from '@/services/fuel/fuelMappingService'
import { getReconciliationSummary, runReconciliation } from '@/services/accountingDocService'

const KIND_LABEL: Record<string, string> = {
  shift_orp: 'Смены → ОРП',
  purchase_ttn: 'ТТН → Поступление',
  ttn_transfer: 'ТТН → Перемещение',
  ttn_assembly: 'ТТН → Комплектация',
  fuel_transfer: 'Перемещение топлива',
  cash_pko: 'Касса → ПКО',
  production: 'Общепит → ОПЗС',
  correction: 'Корректировки',
}
// Воронка выгрузки: этап пакета → 1С
const FUNNEL: { key: string; label: string; cls: string }[] = [
  { key: 'draft', label: 'Готово к отправке', cls: 'text-blue-600 dark:text-blue-400' },
  { key: 'queued', label: 'В очереди', cls: 'text-muted-foreground' },
  { key: 'sent', label: 'Отправлено', cls: 'text-muted-foreground' },
  { key: 'acked', label: 'Загружено в 1С', cls: 'text-emerald-600 dark:text-emerald-400' },
  { key: 'rejected', label: 'Отклонено 1С', cls: 'text-red-500' },
]

const H3 = 'text-xs font-semibold uppercase tracking-wide text-muted-foreground'
const fmtN = (v: number) => (v ?? 0).toLocaleString('ru-RU')

interface PacketStats { total: number; byStatus: Record<string, number>; byKind: Record<string, number> }

export function SyncWith1CPanel() {
  const { company } = useCompany()
  const companyId = company.id
  const qc = useQueryClient()
  const nav = useNavigate()
  const [running, setRunning] = useState(false)
  const [period, setPeriod] = useState<'month' | 'quarter'>('month')
  const from = format(subMonths(new Date(), period === 'month' ? 1 : 3), 'yyyy-MM-dd')
  const to = format(new Date(), 'yyyy-MM-dd')
  const api = isApiEnabled()

  const readiness = useQuery({ queryKey: ['fuel-readiness', from, to], queryFn: () => getFuelReadiness(from, to) })
  const pk = useQuery({
    queryKey: ['export-packets-stats', companyId],
    queryFn: () => get<PacketStats>('/api/export-packets/stats', { company_id: companyId }),
    enabled: api,
  })
  const recon = useQuery({ queryKey: ['reconciliation-summary', companyId], queryFn: () => getReconciliationSummary(companyId) })

  const runRecon = async () => {
    setRunning(true)
    try {
      await runReconciliation(companyId)
      await qc.invalidateQueries({ queryKey: ['reconciliation-summary'] })
    } finally { setRunning(false) }
  }

  const byStatus = pk.data?.byStatus ?? {}
  const byKind = pk.data?.byKind ?? {}
  const rs = recon.data
  const noOneC = !rs || rs.totalAccDocs === 0

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Сверка с 1С</h2>
        <span className="text-xs text-muted-foreground">готовность к загрузке · разница приложение ↔ 1С</span>
        <div className="ml-auto flex gap-1 rounded-lg bg-card p-1">
          {(['month', 'quarter'] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={cn('rounded px-3 py-1 text-xs transition-colors', period === p ? 'bg-primary text-white' : 'text-muted-foreground hover:bg-accent/40')}>
              {p === 'month' ? 'Месяц' : 'Квартал'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Секция 1: Воронка загрузки ── */}
      <Card>
        <CardContent className="pt-4">
          <div className="mb-3 flex items-center gap-2"><Upload className="h-4 w-4 text-primary" /><h3 className={H3}>Воронка загрузки в 1С</h3></div>
          {!api ? (
            <p className="py-4 text-center text-sm text-muted-foreground">Доступно при подключённом API-бэкенде.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-stretch gap-2">
                {FUNNEL.map((f, i) => (
                  <div key={f.key} className="flex items-center gap-2">
                    <div className="min-w-[120px] rounded-lg border border-border bg-background p-3">
                      <div className="text-[11px] text-muted-foreground">{f.label}</div>
                      <div className={cn('mt-0.5 text-xl font-bold tabular-nums', f.cls)}>{fmtN(byStatus[f.key] ?? 0)}</div>
                    </div>
                    {i < FUNNEL.length - 1 && <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground/40" />}
                  </div>
                ))}
              </div>
              {Object.keys(byKind).length > 0 && (
                <table className="mt-3 w-full text-sm">
                  <thead><tr className="border-b border-border/60 text-[11px] text-muted-foreground">
                    <th className="py-1.5 text-left font-medium">Тип документа</th>
                    <th className="py-1.5 text-right font-medium">Пакетов</th>
                  </tr></thead>
                  <tbody>
                    {Object.entries(byKind).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
                      <tr key={k} className="border-b border-border/30">
                        <td className="py-1.5">{KIND_LABEL[k] ?? k}</td>
                        <td className="py-1.5 text-right tabular-nums">{fmtN(n)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* ── Секция 2: Разница приложение ↔ 1С ── */}
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

      {/* ── Секция 3: Требует внимания + переходы ── */}
      <Card>
        <CardContent className="pt-4">
          <div className="mb-3 flex items-center gap-2"><ClipboardCheck className="h-4 w-4 text-primary" /><h3 className={H3}>Требует внимания</h3></div>
          <div className="grid gap-2 sm:grid-cols-3">
            <ActionRow
              label="Не загружено в 1С"
              value={(byStatus.draft ?? 0) + (byStatus.queued ?? 0) + (byStatus.sent ?? 0)}
              hint="готовы, но ещё не в 1С"
              onClick={() => nav('/1c/export')}
              danger={false}
            />
            <ActionRow
              label="Отклонено 1С"
              value={byStatus.rejected ?? 0}
              hint="требуется разбор причины"
              onClick={() => nav('/1c/export')}
              danger={(byStatus.rejected ?? 0) > 0}
            />
            <ActionRow
              label="Расхождения сумм"
              value={rs?.discrepancy ?? 0}
              hint="открыть документы с Δ"
              onClick={() => nav('/1c/documents')}
              danger={(rs?.discrepancy ?? 0) > 0}
            />
          </div>
          {readiness.data && readiness.data.receipts.pending > 0 && (
            <p className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              {fmtN(readiness.data.receipts.pending)} ТТН ещё не проверены — подтвердите приёмку до выгрузки (раздел «Поступления»).
            </p>
          )}
        </CardContent>
      </Card>
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
