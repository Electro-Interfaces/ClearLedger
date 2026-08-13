/**
 * Приём первичных документов — вкладка «Загрузка → Первичка».
 *
 * Файл кладётся не «в папку», а в разбор: система читает таблицу, сопоставляет
 * контрагента и договор с уже заведёнными, сверяет документ с накопленным
 * (закрытые периоды, ранее принятые документы, обычные суммы этого контрагента) —
 * и показывает, что поняла, ДО того как что-то попадёт в учёт.
 *
 * Приём — отдельное действие человека. Проверки делятся на три уровня: «нельзя»
 * блокирует строку, «странно» и «к сведению» только подсвечивают. Система знает
 * не бизнес, а то, что уже загружено, — последнее слово за человеком.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, Ban, Check, Copy, FileUp, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import {
  acceptIntake, getIntakeBatches, getIntakeItems, rejectIntake, uploadIntake,
  type IntakeItemRow,
} from '@/services/intakeDocsService'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

/** Что человек говорит про содержимое файла: вид применяется к строкам без своего. */
const DECLARED = [
  { key: 'sale', label: 'Реализация' },
  { key: 'purchase', label: 'Поступление' },
  { key: 'invoice_out', label: 'Счета покупателям' },
  { key: 'bank_in', label: 'Поступления на счёт' },
  { key: 'bank_out', label: 'Списания со счёта' },
] as const

const STATUS: Record<string, { label: string; cls: string }> = {
  ready: { label: 'готов', cls: 'border-emerald-500/40 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400' },
  warning: { label: 'вопрос', cls: 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400' },
  blocked: { label: 'нельзя', cls: 'border-red-500/40 bg-red-500/5 text-red-600 dark:text-red-400' },
  duplicate: { label: 'дубль', cls: 'border-red-500/40 bg-red-500/5 text-red-600 dark:text-red-400' },
  accepted: { label: 'принят', cls: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600' },
  rejected: { label: 'отклонён', cls: 'border-border text-muted-foreground' },
}

export function IntakeDocs() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [declared, setDeclared] = useState<string>('sale')
  const [batchId, setBatchId] = useState<string | null>(null)

  const batches = useQuery({
    queryKey: ['intake-docs', 'batches', companyId],
    queryFn: () => getIntakeBatches(companyId),
    enabled: !!companyId,
  })
  const items = useQuery({
    queryKey: ['intake-docs', 'items', companyId, batchId],
    queryFn: () => getIntakeItems(companyId, batchId!),
    enabled: !!companyId && !!batchId,
  })

  const upload = useMutation({
    mutationFn: (file: File) => uploadIntake(companyId, file, declared),
    onSuccess: (r) => {
      setBatchId(r.batchId)
      qc.invalidateQueries({ queryKey: ['intake-docs'] })
      if (r.error) toast.error(r.error)
      else toast.success(`Разобрано документов: ${r.items?.length ?? 0}`)
    },
    onError: () => toast.error('Не удалось разобрать файл'),
  })

  const accept = useMutation({
    mutationFn: (ids: string[]) => acceptIntake(companyId, ids),
    onSuccess: (r) => {
      toast.success(`Принято в учёт: ${r.created}${r.skipped ? `, пропущено ${r.skipped}` : ''}`)
      qc.invalidateQueries({ queryKey: ['intake-docs'] })
      qc.invalidateQueries({ queryKey: ['books'] })
    },
    onError: () => toast.error('Не удалось принять документы'),
  })

  const reject = useMutation({
    mutationFn: (ids: string[]) => rejectIntake(companyId, ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['intake-docs'] }),
  })

  const rows = items.data?.rows ?? []
  const acceptable = rows.filter((r) => r.status === 'ready' || r.status === 'warning')

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="text-sm font-medium">Загрузить документы файлом</div>
          <p className="text-[11px] text-muted-foreground">
            Excel или CSV. Колонки распознаются по заголовкам (номер, дата, контрагент,
            ИНН, договор, номенклатура, сумма, НДС) — переименовывать их не нужно.
            В учёт ничего не попадёт, пока вы не примете разбор.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-muted-foreground">Это:</span>
            {DECLARED.map((d) => (
              <button key={d.key} onClick={() => setDeclared(d.key)}
                className={cn('rounded-md border px-2.5 py-1 text-xs transition-colors',
                  declared === d.key
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-muted')}>
                {d.label}
              </button>
            ))}
          </div>
          <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) upload.mutate(f)
              e.target.value = ''
            }} />
          <Button size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
            {upload.isPending
              ? <Loader2 className="size-4 mr-2 animate-spin" />
              : <FileUp className="size-4 mr-2" />}
            Выбрать файл
          </Button>
        </CardContent>
      </Card>

      {rows.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b">
              <span className="text-sm font-medium">Разбор — {rows.length} документов</span>
              <Counter rows={rows} />
              <div className="ml-auto flex gap-2">
                <Button size="sm" variant="outline"
                  disabled={!acceptable.length || accept.isPending}
                  onClick={() => accept.mutate(acceptable.map((r) => r.id))}>
                  <Check className="size-4 mr-1.5" />
                  Принять ({acceptable.length})
                </Button>
                <Button size="sm" variant="ghost"
                  onClick={() => reject.mutate(rows.filter((r) => r.status !== 'accepted')
                    .map((r) => r.id))}>
                  Отклонить всё
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-[11px] uppercase tracking-wider text-muted-foreground">
                  <tr className="border-b">
                    <th className="text-left font-normal px-3 py-2 w-[92px]">Статус</th>
                    <th className="text-left font-normal px-3 py-2">Документ</th>
                    <th className="text-left font-normal px-3 py-2">Контрагент</th>
                    <th className="text-left font-normal px-3 py-2">Договор</th>
                    <th className="text-right font-normal px-3 py-2 w-[130px]">Сумма</th>
                    <th className="text-right font-normal px-3 py-2 w-[80px]">Строк</th>
                    <th className="text-right font-normal px-3 py-2 w-[110px]" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <Row key={r.id} r={r}
                      onAccept={() => accept.mutate([r.id])}
                      onReject={() => reject.mutate([r.id])} />
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground border-b">
            История загрузок
          </div>
          <table className="w-full text-sm">
            <tbody>
              {(batches.data?.rows ?? []).map((b) => (
                <tr key={b.id}
                  onClick={() => setBatchId(b.id)}
                  className={cn('border-b last:border-0 cursor-pointer hover:bg-muted/40',
                    b.id === batchId && 'bg-accent')}>
                  <td className="px-3 py-1.5 max-w-[280px] truncate" title={b.fileName ?? ''}>
                    {b.fileName ?? 'без имени'}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground">{b.uploadedBy}</td>
                  <td className="px-3 py-1.5 text-muted-foreground tabular-nums whitespace-nowrap">
                    {b.createdAt?.slice(0, 16).replace('T', ' ')}
                  </td>
                  <td className="px-3 py-1.5 text-right text-muted-foreground">
                    {b.stats?.items ?? 0} док. · принято {b.accepted}
                  </td>
                </tr>
              ))}
              {(batches.data?.rows ?? []).length === 0 && (
                <tr><td className="px-3 py-3 text-sm text-muted-foreground">
                  Загрузок пока не было
                </td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

function Counter({ rows }: { rows: IntakeItemRow[] }) {
  const by = (s: string) => rows.filter((r) => r.status === s).length
  return (
    <div className="flex flex-wrap gap-1.5 text-[11px]">
      {['ready', 'warning', 'blocked', 'duplicate', 'accepted'].map((s) => {
        const n = by(s)
        if (!n) return null
        return (
          <Badge key={s} variant="outline" className={cn('text-[11px]', STATUS[s]?.cls)}>
            {STATUS[s]?.label}: {n}
          </Badge>
        )
      })}
    </div>
  )
}

function Row({ r, onAccept, onReject }: {
  r: IntakeItemRow; onAccept: () => void; onReject: () => void
}) {
  const st = STATUS[r.status] ?? { label: r.status, cls: '' }
  const blocked = r.status === 'blocked' || r.status === 'duplicate'
  const done = r.status === 'accepted' || r.status === 'rejected'
  return (
    <>
      <tr className="border-b hover:bg-muted/40">
        <td className="px-3 py-1.5">
          <span className={cn('rounded border px-1.5 py-0.5 text-[11px]', st.cls)}>{st.label}</span>
        </td>
        <td className="px-3 py-1.5 whitespace-nowrap">
          {r.number ?? '—'} <span className="text-muted-foreground">от {r.date ?? '—'}</span>
        </td>
        <td className="px-3 py-1.5 max-w-[260px] truncate" title={r.counterpartyName ?? ''}>
          {r.counterpartyName ?? '—'}
          {!r.counterpartyId && r.counterpartyName && (
            <span className="ml-1.5 text-[10px] text-amber-600 dark:text-amber-400">новый</span>
          )}
        </td>
        <td className="px-3 py-1.5 max-w-[200px] truncate text-muted-foreground"
          title={r.contractName ?? ''}>
          {r.contractName ?? '—'}
          {r.contractName && !r.contractId && (
            <span className="ml-1.5 text-[10px] text-amber-600 dark:text-amber-400">нет</span>
          )}
        </td>
        <td className="px-3 py-1.5 text-right tabular-nums whitespace-nowrap">
          {money.format(r.amount)}
          {!!r.vat && <span className="block text-[10px] text-muted-foreground">
            НДС {money.format(r.vat)}
          </span>}
        </td>
        <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
          {r.lines.length}
        </td>
        <td className="px-3 py-1.5 text-right whitespace-nowrap">
          {!done && (
            <>
              <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]"
                disabled={blocked} onClick={onAccept} title={blocked ? 'Строка заблокирована' : ''}>
                <Check className="size-3" />
              </Button>
              <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={onReject}>
                <Ban className="size-3" />
              </Button>
            </>
          )}
        </td>
      </tr>
      {(r.checks ?? []).length > 0 && (
        <tr className="border-b last:border-0">
          <td />
          <td colSpan={6} className="px-3 pb-1.5">
            <div className="flex flex-col gap-0.5">
              {r.checks.map((c, i) => (
                <div key={i} className={cn('flex items-start gap-1.5 text-[11px]',
                  c.level === 'error' ? 'text-red-600 dark:text-red-400'
                    : c.level === 'warning' ? 'text-amber-700 dark:text-amber-400'
                    : 'text-muted-foreground')}>
                  {c.code === 'duplicate'
                    ? <Copy className="size-3 mt-0.5 shrink-0" />
                    : <AlertTriangle className="size-3 mt-0.5 shrink-0" />}
                  {c.text}
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
