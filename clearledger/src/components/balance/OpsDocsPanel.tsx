/**
 * «Документы» — вся входящая первичка контрагентов в одном месте.
 *
 * Реестр закрытия отвечает на вопрос «чего не хватает за месяц». Этот экран
 * отвечает на другой: «что вообще к нам пришло». Документ может лежать
 * непривязанным (скан прислали, а к какому объекту он относится — неясно),
 * может закрывать десять ожиданий сразу, а может ждать скана.
 *
 * Фильтр по умолчанию — непривязанные: разобранные документы работы не требуют.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { FileText, Loader2, Paperclip, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { fmtN } from './balanceCalc'
import {
  attachOpsDocFile, getOpsDocs, opsDocFileUrl, type OpsDoc,
} from '@/services/opsService'

const DOC_LABEL: Record<string, string> = {
  act: 'Акт', upd: 'УПД', invoice: 'Счёт', sf: 'Счёт-фактура',
  torg12: 'ТОРГ-12', report: 'Расчёт', other: 'Иное',
}

const CHANNEL_LABEL: Record<string, string> = {
  email: 'почта', edo: 'ЭДО', manual: 'вручную', portal: 'портал',
}

const MATCH_LABEL: Record<string, { label: string; tone: string }> = {
  unmatched: { label: 'не привязан', tone: 'text-amber-600 dark:text-amber-400' },
  auto: { label: 'привязан автоматически', tone: 'text-emerald-600 dark:text-emerald-400' },
  manual: { label: 'привязан вручную', tone: 'text-emerald-600 dark:text-emerald-400' },
  rejected: { label: 'отклонён', tone: 'text-muted-foreground' },
}

const money = (v: number | null) => (v === null ? '—' : fmtN(Math.round(v)))

export function OpsDocsPanel() {
  const { companyId } = useCompany()
  const [filter, setFilter] = useState<string>('')

  const q = useQuery({
    queryKey: ['ops-docs', companyId, filter],
    queryFn: () => getOpsDocs(companyId!, filter || undefined),
    enabled: !!companyId,
  })

  if (q.isLoading) {
    return <div className="flex justify-center py-16">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  }
  if (q.isError) {
    return <div className="p-6 text-sm text-red-600 dark:text-red-400">
      Не удалось загрузить документы. Обновите страницу.
    </div>
  }

  const docs = q.data?.docs ?? []
  const unmatched = docs.filter((d) => d.matchStatus === 'unmatched').length
  const noFile = docs.filter((d) => !d.fileId).length

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border border-border bg-muted/60 p-0.5">
          {([['', 'Все'], ['unmatched', 'Не привязанные'],
             ['manual', 'Привязанные']] as const).map(([v, label]) => (
            <button key={v || 'all'} type="button" onClick={() => setFilter(v)}
              className={`rounded-[5px] px-3 py-1.5 text-sm transition-colors ${
                filter === v ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'}`}>{label}</button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted-foreground">
          всего {docs.length}
          {unmatched > 0 && ` · не привязано ${unmatched}`}
          {noFile > 0 && ` · без скана ${noFile}`}
        </span>
      </div>

      {docs.length === 0 ? (
        <Card><CardContent className="space-y-2 py-10 text-center text-sm text-muted-foreground">
          <FileText className="mx-auto h-8 w-8 opacity-40" />
          <p>Документов пока нет.</p>
          <p className="text-xs">
            Документ заводится из строки реестра на экране «Закрытие месяца» —
            там уже известны контрагент, договор, период и ожидаемая сумма.
            Приём почтой и через ЭДО подключается отдельно.
          </p>
        </CardContent></Card>
      ) : (
        <Card><CardContent className="p-0">
          {/* Узкий экран: карточки — восемь колонок в телефон не помещаются. */}
          <div className="divide-y divide-border sm:hidden">
            {docs.map((d) => <DocCard key={d.id} doc={d} />)}
          </div>

          <div className="hidden overflow-x-auto sm:block">
            <Table>
              <TableHeader><TableRow>
                <TableHead>Документ</TableHead>
                <TableHead>Контрагент</TableHead>
                <TableHead>Период</TableHead>
                <TableHead className="text-right">Сумма</TableHead>
                <TableHead>Канал</TableHead>
                <TableHead>Состояние</TableHead>
                <TableHead className="text-right">Строк</TableHead>
                <TableHead>Скан</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {docs.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell>
                      <div className="font-medium">
                        {DOC_LABEL[d.docType] ?? d.docType}
                        {d.number && ` № ${d.number}`}
                      </div>
                      {d.docDate && (
                        <div className="text-xs text-muted-foreground">от {d.docDate}</div>
                      )}
                    </TableCell>
                    <TableCell className="max-w-[220px] truncate"
                      title={d.counterpartyName ?? undefined}>
                      {d.counterpartyName ?? '—'}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm">
                      {d.period ? d.period.slice(0, 7)
                        : d.periodFrom ? `${d.periodFrom} — ${d.periodTo ?? '…'}` : '—'}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{money(d.amountGross)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {CHANNEL_LABEL[d.channel] ?? d.channel}
                    </TableCell>
                    <TableCell className={`text-xs ${MATCH_LABEL[d.matchStatus]?.tone ?? ''}`}>
                      {MATCH_LABEL[d.matchStatus]?.label ?? d.matchStatus}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {d.linkedCharges || <span className="text-amber-600 dark:text-amber-400">0</span>}
                    </TableCell>
                    <TableCell><FileCell doc={d} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent></Card>
      )}

      <p className="text-xs text-muted-foreground">
        «Строк» — сколько ожиданий закрыто этим документом. Ноль означает, что
        документ есть, но ни один месяц им пока не закрыт. Один документ может
        закрывать несколько объектов сразу — например УПД на всю сеть.
      </p>
    </div>
  )
}

function DocCard({ doc }: { doc: OpsDoc }) {
  return (
    <div className="space-y-1 p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium">
          {DOC_LABEL[doc.docType] ?? doc.docType}{doc.number && ` № ${doc.number}`}
        </span>
        <span className="shrink-0 tabular-nums">{money(doc.amountGross)} ₽</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {doc.counterpartyName && <span>{doc.counterpartyName}</span>}
        {doc.period && <span>· {doc.period.slice(0, 7)}</span>}
        <span className={MATCH_LABEL[doc.matchStatus]?.tone}>
          · {MATCH_LABEL[doc.matchStatus]?.label ?? doc.matchStatus}
        </span>
        <FileCell doc={doc} />
      </div>
    </div>
  )
}

/** Скан: ссылка, если есть, иначе кнопка загрузки. */
function FileCell({ doc }: { doc: OpsDoc }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)

  const send = useMutation({
    mutationFn: (file: File) => attachOpsDocFile(companyId!, doc.id, file),
    onSuccess: () => {
      toast.success('Скан прикреплён')
      qc.invalidateQueries({ queryKey: ['ops-docs', companyId] })
    },
    onError: (e: unknown) => toast.error(`Ошибка: ${(e as Error).message}`),
  })

  if (doc.fileId) {
    return (
      <a href={opsDocFileUrl(doc.fileId)} target="_blank" rel="noreferrer"
        className="inline-flex items-center gap-1 text-xs hover:underline">
        <Paperclip className="h-3 w-3" />открыть
      </a>
    )
  }
  return (
    <>
      <input ref={inputRef} type="file" className="hidden"
        accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.doc,.docx"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) send.mutate(file)
          e.target.value = ''
        }} />
      <Button size="sm" variant="ghost" className="h-7 gap-1 px-2 text-xs"
        disabled={send.isPending} onClick={() => inputRef.current?.click()}
        title="Прикрепить скан документа">
        {send.isPending ? <Loader2 className="h-3 w-3 animate-spin" />
          : <Upload className="h-3 w-3" />}
        скан
      </Button>
    </>
  )
}
