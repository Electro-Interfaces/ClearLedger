/**
 * «Кандидаты» — воронка возможностей по направлениям роста.
 *
 * Кандидат — это не сценарий. Сценарий проверяет действие замером; кандидат —
 * возможность, которую ещё предстоит оценить и либо взять в работу, либо отклонить
 * с причиной. Причина обязательна: список отказов без причин через полгода ничему
 * не учит, а вопрос «почему мы тогда не пошли в Иркутск» задают именно через полгода.
 *
 * Взятый в работу кандидат уходит в исполнительный контур: стройка — площадкой в
 * «Проекты», тариф и акция — сценарием с замером.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Lightbulb } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import {
  createGrowthLead, listGrowthLeads, patchGrowthLead, type GrowthLead,
} from '@/services/marketService'

const TRACKS: Record<string, string> = {
  build: 'своя стройка',
  roaming: 'роуминг с чужой сетью',
  franchise: 'франшиза: чужая сеть на нашем обслуживании',
  corporate: 'корпоративные продажи',
  loyalty: 'программа лояльности',
}

const STATUSES: Record<string, string> = {
  new: 'новый',
  working: 'в проработке',
  in_project: 'взят в работу',
  rejected: 'отклонён',
  done: 'сделано',
}

function LeadRow({ lead, onMove }: {
  lead: GrowthLead; onMove: (id: string, status: string, reason?: string) => void
}) {
  const [reason, setReason] = useState('')
  const [asking, setAsking] = useState(false)
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-medium">{lead.title}</span>
          <span className="text-xs text-muted-foreground">
            {lead.trackLabel}
            {lead.subjectRef ? ` · ${lead.subjectRef}` : ''}
            {lead.ownerName ? ` · ${lead.ownerName}` : ''}
          </span>
        </div>
        {lead.note && <p className="text-xs text-muted-foreground">{lead.note}</p>}
        {lead.rejectReason && (
          <p className="text-xs text-warning">Отклонён: {lead.rejectReason}</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Select value={lead.status}
            onValueChange={(v) => (v === 'rejected' ? setAsking(true) : onMove(lead.id, v))}>
            <SelectTrigger className="h-7 w-[170px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(STATUSES).map(([k, label]) => (
                <SelectItem key={k} value={k}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {asking && (
            <>
              <Input value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Почему отклоняем — это и есть знание"
                className="h-7 w-[280px] text-xs" />
              <Button size="sm" variant="outline" disabled={!reason}
                onClick={() => { onMove(lead.id, 'rejected', reason); setAsking(false) }}>
                Отклонить
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function MarketLeadsPanel() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [track, setTrack] = useState('all')
  const [title, setTitle] = useState('')
  const [newTrack, setNewTrack] = useState('build')

  const list = useQuery({
    queryKey: ['market-growth-leads', companyId, track],
    queryFn: () => listGrowthLeads(companyId, track === 'all' ? undefined : { track }),
    enabled: !!companyId,
  })
  const create = useMutation({
    mutationFn: () => createGrowthLead(companyId, { track: newTrack, title }),
    onSuccess: () => {
      setTitle('')
      qc.invalidateQueries({ queryKey: ['market-growth-leads', companyId] })
    },
  })
  const move = useMutation({
    mutationFn: ({ id, status, reason }: { id: string; status: string; reason?: string }) =>
      patchGrowthLead(companyId, id, { status, ...(reason ? { rejectReason: reason } : {}) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['market-growth-leads', companyId] })
      qc.invalidateQueries({ queryKey: ['market-growth-overview', companyId] })
    },
  })

  const rows = list.data?.leads ?? []
  const open = rows.filter((r) => r.status === 'new' || r.status === 'working')
  const taken = rows.filter((r) => r.status === 'in_project' || r.status === 'done')
  const rejected = rows.filter((r) => r.status === 'rejected')

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Lightbulb className="size-4 text-primary" aria-hidden />
            {rows.length === 0
              ? 'Кандидатов пока нет: возможности заводятся отсюда или из «Белых пятен» и «Партнёрства».'
              : `В работе ${open.length}, взято ${taken.length}, отклонено ${rejected.length}.`}
          </span>
          <Select value={track} onValueChange={setTrack}>
            <SelectTrigger className="h-8 w-[240px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все направления</SelectItem>
              {Object.entries(TRACKS).map(([k, label]) => (
                <SelectItem key={k} value={k}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 p-3">
          <Input value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="Возможность: «войти в Архангельск роумингом с Россетями»"
            className="h-8 w-[420px] text-xs" />
          <Select value={newTrack} onValueChange={setNewTrack}>
            <SelectTrigger className="h-8 w-[240px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(TRACKS).map(([k, label]) => (
                <SelectItem key={k} value={k}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button size="sm" disabled={!title || create.isPending} onClick={() => create.mutate()}>
            Завести кандидата
          </Button>
        </CardContent>
      </Card>

      <div className="min-h-0 flex-1 space-y-2 overflow-auto">
        {[['В работе', open], ['Взяты', taken], ['Отклонены', rejected]].map(
          ([label, group]) => (group as GrowthLead[]).length > 0 && (
            <div key={label as string} className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {label as string}
              </div>
              {(group as GrowthLead[]).map((lead) => (
                <LeadRow key={lead.id} lead={lead}
                  onMove={(id, status, reason) => move.mutate({ id, status, reason })} />
              ))}
            </div>
          ))}
      </div>
    </div>
  )
}
