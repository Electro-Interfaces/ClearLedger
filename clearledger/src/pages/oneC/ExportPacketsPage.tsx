/**
 * Страница «1С → Выгрузка» — L3 слой (см. docs/sverka-spec.md §0).
 * Пакеты данных, подготовленные TradeLedger для загрузки в БП ГИГ
 * через её расширение TradeLedger.cfe (тянет /queue, квитирует /ack).
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import { Package, Send, CheckCircle2, XCircle, Loader2, Trash2, RefreshCw, Inbox } from 'lucide-react'
import { toast } from 'sonner'
import { format } from 'date-fns'

import { useCompany } from '@/contexts/CompanyContext'
import { get, post, patch, del } from '@/services/apiClient'

interface ExportPacket {
  id: string
  companyId: string
  kind: string
  status: string
  sourceEntryIds: string[]
  payload: Record<string, unknown>
  sentAt?: string | null
  ackedAt?: string | null
  rejectReason?: string | null
  targetDocId?: string | null
  createdAt: string
  updatedAt: string
}

interface PacketStats {
  total: number
  byStatus: Record<string, number>
  byKind: Record<string, number>
}

const KINDS = [
  { value: 'all',           label: 'Все типы' },
  { value: 'shift_orp',     label: 'Сменный ОРП' },
  { value: 'purchase_ttn',  label: 'ТТН поступления' },
  { value: 'cash_pko',      label: 'Касса ПКО' },
  { value: 'production',    label: 'Общепит ОПЗС' },
  { value: 'correction',    label: 'Корректировка' },
]

const STATUSES = [
  { value: 'all',      label: 'Все статусы' },
  { value: 'draft',    label: 'Черновик' },
  { value: 'queued',   label: 'В очереди' },
  { value: 'sent',     label: 'Отдано в 1С' },
  { value: 'acked',    label: 'Принято 1С' },
  { value: 'rejected', label: 'Отклонено' },
]

const STATUS_STYLE: Record<string, string> = {
  draft:    'border-zinc-600 text-zinc-400',
  queued:   'border-blue-400/50 text-blue-300/80',
  sent:     'border-amber-400/50 text-amber-300/80',
  acked:    'border-emerald-400/50 text-emerald-300/80',
  rejected: 'border-red-400/50 text-red-300/80',
}

export function ExportPacketsPage() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [kind, setKind] = useState('all')
  const [pktStatus, setPktStatus] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selected, setSelected] = useState<ExportPacket | null>(null)

  const { data: packets = [], isLoading, refetch } = useQuery<ExportPacket[]>({
    queryKey: ['packets', companyId, kind, pktStatus],
    queryFn: () => get<ExportPacket[]>('/api/export-packets', {
      company_id: companyId,
      kind: kind === 'all' ? undefined : kind,
      status: pktStatus === 'all' ? undefined : pktStatus,
    }),
  })

  const { data: stats } = useQuery<PacketStats>({
    queryKey: ['packets-stats', companyId],
    queryFn: () => get<PacketStats>('/api/export-packets/stats', { company_id: companyId }),
  })

  const buildMut = useMutation({
    mutationFn: () => post<{ created: number; skipped: number; considered_clean_entries: number }>(
      `/api/export-packets/build?company_id=${companyId}` +
      (dateFrom ? `&date_from=${dateFrom}` : '') +
      (dateTo ? `&date_to=${dateTo}` : ''),
    ),
    onSuccess: (r) => {
      toast.success(`Собрано ${r.created} новых пакетов (из ${r.considered_clean_entries} L2-записей, пропущено ${r.skipped})`)
      qc.invalidateQueries({ queryKey: ['packets', companyId] })
      qc.invalidateQueries({ queryKey: ['packets-stats', companyId] })
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Не удалось собрать пакеты'),
  })

  const sendToQueueMut = useMutation({
    mutationFn: (id: string) => patch(`/api/export-packets/${id}`, { status: 'queued' }),
    onSuccess: () => { refetch(); qc.invalidateQueries({ queryKey: ['packets-stats', companyId] }) },
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => del(`/api/export-packets/${id}`),
    onSuccess: () => {
      toast.success('Пакет удалён')
      refetch(); qc.invalidateQueries({ queryKey: ['packets-stats', companyId] })
    },
  })

  return (
    <div className="space-y-4 max-w-7xl">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Выгрузка в 1С (L3)</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Пакеты данных подготовленные TradeLedger для загрузки в БП ГИГ.
            Расширение TradeLedger.cfe тянет их через GET /queue и квитирует через POST /ack.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            placeholder="С" className="h-8 text-xs w-32" />
          <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            placeholder="По" className="h-8 text-xs w-32" />
          <Button size="sm" onClick={() => buildMut.mutate()} disabled={buildMut.isPending}
            className="gap-1.5">
            {buildMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Package className="h-3.5 w-3.5" />}
            Собрать пакеты из L2
          </Button>
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          <Card className="py-2 gap-0">
            <CardContent className="p-3">
              <div className="text-[10px] text-muted-foreground uppercase">Всего</div>
              <div className="text-lg font-semibold mt-0.5">{stats.total.toLocaleString('ru-RU')}</div>
            </CardContent>
          </Card>
          {(['draft','queued','sent','acked','rejected'] as const).map((s) => (
            <Card key={s} className="py-2 gap-0">
              <CardContent className="p-3">
                <div className="text-[10px] text-muted-foreground uppercase truncate">
                  {STATUSES.find((x) => x.value === s)?.label}
                </div>
                <div className="text-lg font-semibold mt-0.5">{(stats.byStatus[s] ?? 0).toLocaleString('ru-RU')}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm">Фильтры</CardTitle>
          <CardDescription className="text-xs">
            Тип пакета и статус жизненного цикла.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex gap-2 flex-wrap">
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger className="h-8 text-xs w-40"><SelectValue /></SelectTrigger>
              <SelectContent>{KINDS.map((k) => (
                <SelectItem key={k.value} value={k.value} className="text-xs">{k.label}</SelectItem>
              ))}</SelectContent>
            </Select>
            <Select value={pktStatus} onValueChange={setPktStatus}>
              <SelectTrigger className="h-8 text-xs w-40"><SelectValue /></SelectTrigger>
              <SelectContent>{STATUSES.map((s) => (
                <SelectItem key={s.value} value={s.value} className="text-xs">{s.label}</SelectItem>
              ))}</SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-2">
            <Inbox className="h-4 w-4 text-muted-foreground" />
            Пакеты <Badge variant="outline" className="text-[10px] font-mono">{packets.length}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {isLoading && <Loader2 className="h-5 w-5 animate-spin mx-auto my-4" />}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="h-7 text-[10px] w-32">Тип</TableHead>
                <TableHead className="h-7 text-[10px]">Описание (marker)</TableHead>
                <TableHead className="h-7 text-[10px] w-24">Статус</TableHead>
                <TableHead className="h-7 text-[10px] w-32">Создан</TableHead>
                <TableHead className="h-7 text-[10px] w-32">Отдан</TableHead>
                <TableHead className="h-7 text-[10px] w-32">Принят</TableHead>
                <TableHead className="h-7 text-[10px] w-12">L4</TableHead>
                <TableHead className="h-7 text-[10px] w-24"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {packets.map((p) => (
                <TableRow key={p.id} className="text-xs cursor-pointer hover:bg-muted/40"
                  onClick={() => setSelected(p)}>
                  <TableCell className="py-1.5">
                    <Badge variant="outline" className="text-[9px] h-4 px-1 font-mono">{p.kind}</Badge>
                  </TableCell>
                  <TableCell className="py-1.5 text-[11px] font-mono truncate max-w-[260px]"
                    title={String(p.payload?.marker ?? '')}>
                    {String(p.payload?.marker ?? '—')}
                  </TableCell>
                  <TableCell className="py-1.5">
                    <Badge variant="outline" className={`text-[9px] h-4 px-1 ${STATUS_STYLE[p.status] ?? ''}`}>
                      {STATUSES.find((s) => s.value === p.status)?.label ?? p.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="py-1.5 text-[10px] text-muted-foreground">
                    {format(new Date(p.createdAt), 'dd.MM HH:mm')}
                  </TableCell>
                  <TableCell className="py-1.5 text-[10px] text-muted-foreground">
                    {p.sentAt ? format(new Date(p.sentAt), 'dd.MM HH:mm') : '—'}
                  </TableCell>
                  <TableCell className="py-1.5 text-[10px] text-muted-foreground">
                    {p.ackedAt ? format(new Date(p.ackedAt), 'dd.MM HH:mm') : '—'}
                  </TableCell>
                  <TableCell className="py-1.5">
                    {p.targetDocId
                      ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                      : <span className="text-muted-foreground text-[10px]">—</span>}
                  </TableCell>
                  <TableCell className="py-1.5 text-right" onClick={(e) => e.stopPropagation()}>
                    {p.status === 'draft' && (
                      <Button size="sm" variant="ghost" className="h-6 w-6 p-0"
                        title="Поставить в очередь"
                        onClick={() => sendToQueueMut.mutate(p.id)}>
                        <Send className="h-3 w-3" />
                      </Button>
                    )}
                    {(p.status === 'draft' || p.status === 'rejected') && (
                      <Button size="sm" variant="ghost" className="h-6 w-6 p-0 text-destructive"
                        onClick={() => { if (confirm('Удалить пакет?')) deleteMut.mutate(p.id) }}>
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {!isLoading && packets.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-[11px] text-muted-foreground py-6">
                    Пакетов нет. Нажми «Собрать пакеты из L2» — он создаст drafts из подтверждённых документов.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <SheetContent className="!max-w-xl p-0 overflow-y-auto">
          {selected && (
            <>
              <SheetHeader className="p-4 pb-2">
                <SheetTitle className="text-base flex items-center gap-2">
                  <Package className="h-4 w-4" />
                  {selected.kind}
                  <Badge variant="outline" className={`text-[9px] h-4 px-1 ml-2 ${STATUS_STYLE[selected.status] ?? ''}`}>
                    {selected.status}
                  </Badge>
                </SheetTitle>
                <SheetDescription className="text-xs font-mono">
                  {String(selected.payload?.marker ?? selected.id)}
                </SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-6 space-y-3">
                <Card className="py-3 gap-1">
                  <CardHeader className="pb-0">
                    <CardTitle className="text-xs uppercase text-muted-foreground">Метаданные</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                    <div className="text-muted-foreground">ID</div><div className="font-mono text-[10px]">{selected.id}</div>
                    <div className="text-muted-foreground">Создан</div><div>{format(new Date(selected.createdAt), 'dd.MM.yyyy HH:mm:ss')}</div>
                    <div className="text-muted-foreground">Отдан в 1С</div><div>{selected.sentAt ? format(new Date(selected.sentAt), 'dd.MM.yyyy HH:mm:ss') : '—'}</div>
                    <div className="text-muted-foreground">Квитировано</div><div>{selected.ackedAt ? format(new Date(selected.ackedAt), 'dd.MM.yyyy HH:mm:ss') : '—'}</div>
                    <div className="text-muted-foreground">Target doc</div><div className="font-mono text-[10px]">{selected.targetDocId ?? '—'}</div>
                    <div className="text-muted-foreground">L2-источников</div><div>{selected.sourceEntryIds.length}</div>
                    {selected.rejectReason && (<>
                      <div className="text-muted-foreground">Reject</div>
                      <div className="text-destructive">{selected.rejectReason}</div>
                    </>)}
                  </CardContent>
                </Card>
                <Card className="py-3 gap-1">
                  <CardHeader className="pb-0">
                    <CardTitle className="text-xs uppercase text-muted-foreground">Payload (то что выгружается в 1С)</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <pre className="text-[10px] font-mono bg-muted/40 p-2 rounded overflow-x-auto">
{JSON.stringify(selected.payload, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
                <Card className="py-3 gap-1">
                  <CardHeader className="pb-0">
                    <CardTitle className="text-xs uppercase text-muted-foreground">L2 источники</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    {selected.sourceEntryIds.length === 0
                      ? <p className="text-[10px] text-muted-foreground italic">нет</p>
                      : (
                        <div className="space-y-0.5">
                          {selected.sourceEntryIds.map((id) => (
                            <div key={id} className="font-mono text-[10px]">{id}</div>
                          ))}
                        </div>
                      )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
