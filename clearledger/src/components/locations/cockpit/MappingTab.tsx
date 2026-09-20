/**
 * «Маппинг» станции — под какими идентификаторами она известна другим системам.
 *
 * Одна станция живёт в полудюжине систем, и в каждой у неё свой ключ: номер в
 * витрине АСУиМ, asset_id в HubEx, адрес OCPP в зарядной сети, объект
 * обслуживания в «Поддержке», идентификатор площадки в роуминге OCPI. Пока это
 * лежало по углам паспорта, вопрос «почему сессии этой станции не сходятся с
 * реестром» решался запросом в базу.
 *
 * Три блока, и смешивать их нельзя (СТО, `docs/OBJECTS.md` §2 и §4):
 *
 * - **свои** — ключ объекта, код, номер станции, заводской и инвентарный
 *   номера. Назначаем мы;
 * - **из загрузки** — следы источника: что приехало в снимке и правится
 *   источником, а не руками;
 * - **реестр соответствий** — то, что ведём сами: система, роль ключа,
 *   значение, период, кто внёс. Закрывается датой, а не удаляется, и одно
 *   значение не может в один период принадлежать двум объектам.
 *
 * Роуминг OCPI — те же записи реестра с системой `ocpi`, вынесенные наверх
 * отдельным блоком: их спрашивают чаще всего и отдельно от остального.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Globe, KeyRound, Link2, Loader2, Plus, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import {
  addStationExternalId, closeStationExternalId, getStationMapping,
  type MappingRow,
} from '@/services/opsService'
import { SectionCard, ScrollTab } from './shared'

const дата = (iso?: string | null) => iso ? iso.split('-').reverse().join('.') : null

/** Строка идентификатора: система, роль, значение и происхождение. */
function Ключ({ r, onClose }: { r: MappingRow; onClose?: () => void }) {
  const закрыт = !!r.validTo
  return (
    <div className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border/30 py-2 text-sm last:border-0 ${
      закрыт ? 'opacity-50' : ''}`}>
      <span className="min-w-0 flex-1">
        <span className="font-mono font-medium break-all">{r.value}</span>
        {r.note && <span className="ml-2 text-xs text-muted-foreground">{r.note}</span>}
      </span>
      <span className="text-xs text-muted-foreground">{r.roleLabel}</span>
      {r.validFrom && (
        <span className="text-xs text-muted-foreground">
          с {дата(r.validFrom)}{r.validTo && ` по ${дата(r.validTo)}`}
        </span>
      )}
      {r.author && <span className="text-xs text-muted-foreground">{r.author}</span>}
      {onClose && !закрыт && (
        <Button size="sm" variant="ghost" className="h-6 px-1.5 text-xs"
          title="Закрыть соответствие датой" onClick={onClose}>
          <X className="size-3.5" />
        </Button>
      )}
    </div>
  )
}

/** Блок «система → её ключи». */
function Система({ label, rows, onClose }: {
  label: string; rows: MappingRow[]; onClose?: (r: MappingRow) => void
}) {
  return (
    <div className="space-y-0.5">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      {rows.map((r, i) => (
        <Ключ key={`${r.value}-${i}`} r={r}
          onClose={onClose && r.id ? () => onClose(r) : undefined} />
      ))}
    </div>
  )
}

function погруппам(rows: MappingRow[]): [string, MappingRow[]][] {
  const m = new Map<string, MappingRow[]>()
  for (const r of rows) {
    const ключ = r.systemLabel
    m.set(ключ, [...(m.get(ключ) ?? []), r])
  }
  return [...m.entries()]
}

export function MappingTab({ location }: { location: { id: string } }) {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const [окно, setОкно] = useState(false)
  const [система, setСистема] = useState('ocpi')
  const [роль, setРоль] = useState('location')
  const [значение, setЗначение] = useState('')
  const [заметка, setЗаметка] = useState('')

  const q = useQuery({
    queryKey: ['station-mapping', companyId, location.id],
    queryFn: () => getStationMapping(companyId, location.id),
    enabled: !!companyId,
    staleTime: 60_000,
  })

  const добавить = useMutation({
    mutationFn: () => addStationExternalId(companyId, location.id, {
      system: система, role: роль, value: значение.trim(),
      note: заметка.trim() || undefined,
    }),
    onSuccess: () => {
      toast.success('Соответствие заведено')
      void qc.invalidateQueries({ queryKey: ['station-mapping', companyId, location.id] })
      setОкно(false); setЗначение(''); setЗаметка('')
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось завести соответствие'),
  })

  const закрыть = useMutation({
    mutationFn: (id: string) => closeStationExternalId(companyId, location.id, id),
    onSuccess: () => {
      toast.success('Соответствие закрыто датой')
      void qc.invalidateQueries({ queryKey: ['station-mapping', companyId, location.id] })
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось закрыть'),
  })

  if (q.isLoading) {
    return <ScrollTab><div className="flex justify-center py-10">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div></ScrollTab>
  }
  if (!q.data?.found) {
    return <ScrollTab>
      <p className="p-4 text-sm text-muted-foreground">Объект не найден в реестре.</p>
    </ScrollTab>
  }

  const d = q.data
  const действующие = d.registry.filter((r) => !r.validTo)
  const закрытые = d.registry.filter((r) => r.validTo)

  return (
    <ScrollTab cols={2}>
      <SectionCard title="Наши идентификаторы" icon={KeyRound}>
        {d.own.map((r, i) => <Ключ key={i} r={r} />)}
      </SectionCard>

      {/* Роуминг наверху: его спрашивают чаще прочего и отдельно от остального. */}
      <SectionCard title="Роуминг OCPI" icon={Globe}
        action={
          <Button size="sm" variant="outline" className="h-7 text-xs"
            onClick={() => { setСистема('ocpi'); setРоль('location'); setОкно(true) }}>
            <Plus className="mr-1 size-3.5" />Добавить ключ
          </Button>
        }>
        {d.roaming.length > 0 ? (
          d.roaming.map((r, i) => (
            <Ключ key={i} r={r} onClose={r.id ? () => закрыть.mutate(r.id!) : undefined} />
          ))
        ) : (
          <p className="text-sm text-muted-foreground">
            Станция в роуминге не заявлена. Когда площадку отдают партнёрам по OCPI,
            сюда заводятся идентификатор оператора (party id), площадки и точек
            отпуска — по ним сходятся чужие сессии.
          </p>
        )}
      </SectionCard>

      <SectionCard title="Из загрузки" icon={Link2}>
        <p className="mb-2 text-xs text-muted-foreground">
          Пришло вместе с данными и правится источником, а не здесь.
        </p>
        <div className="space-y-3">
          {погруппам(d.snapshot).map(([label, rows]) => (
            <Система key={label} label={label} rows={rows} />
          ))}
          {d.snapshot.length === 0 && (
            <p className="text-sm text-muted-foreground">Внешних ключей в снимке нет.</p>
          )}
        </div>
      </SectionCard>

      <SectionCard title="Реестр соответствий" icon={KeyRound}
        action={
          <Button size="sm" variant="outline" className="h-7 text-xs"
            onClick={() => { setСистема('asuim'); setРоль('station'); setОкно(true) }}>
            <Plus className="mr-1 size-3.5" />Добавить
          </Button>
        }>
        <p className="mb-2 text-xs text-muted-foreground">
          Ведём сами: система, роль ключа, значение и период. Запись закрывается
          датой, а не удаляется.
        </p>
        <div className="space-y-3">
          {погруппам(действующие).map(([label, rows]) => (
            <Система key={label} label={label} rows={rows}
              onClose={(r) => r.id && закрыть.mutate(r.id)} />
          ))}
          {действующие.length === 0 && (
            <p className="text-sm text-muted-foreground">Соответствий не заведено.</p>
          )}
          {закрытые.length > 0 && (
            <details className="pt-1">
              <summary className="cursor-pointer text-xs text-muted-foreground">
                Закрытые ({закрытые.length})
              </summary>
              <div className="mt-1 space-y-3">
                {погруппам(закрытые).map(([label, rows]) => (
                  <Система key={label} label={label} rows={rows} />
                ))}
              </div>
            </details>
          )}
        </div>
      </SectionCard>

      <div className="text-xs text-muted-foreground">{d.note}</div>

      <Dialog open={окно} onOpenChange={(v) => { if (!v && !добавить.isPending) setОкно(false) }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Соответствие внешней системы</DialogTitle>
            <DialogDescription>
              Значение не может в один период принадлежать двум объектам — если
              ключ уже занят, система об этом скажет и назовёт объект.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="map-sys">Система</Label>
                <Select value={система} onValueChange={setСистема}>
                  <SelectTrigger id="map-sys"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {d.systems.filter((s) => s.code !== 'own').map((s) => (
                      <SelectItem key={s.code} value={s.code}>{s.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="map-role">Что это за ключ</Label>
                <Select value={роль} onValueChange={setРоль}>
                  <SelectTrigger id="map-role"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {d.roles.map((r) => (
                      <SelectItem key={r.code} value={r.code}>{r.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="map-val">Значение</Label>
              <Input id="map-val" value={значение} onChange={(e) => setЗначение(e.target.value)}
                placeholder="RU*RHY*L0042" className="font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="map-note">Основание или пояснение</Label>
              <Input id="map-note" value={заметка} onChange={(e) => setЗаметка(e.target.value)}
                placeholder="Договор роуминга с … от 12.03.2026" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setОкно(false)}
              disabled={добавить.isPending}>Отмена</Button>
            <Button onClick={() => добавить.mutate()}
              disabled={добавить.isPending || значение.trim().length < 1}>
              {добавить.isPending && <Loader2 className="mr-1.5 size-4 animate-spin" />}
              Завести
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {закрыть.isPending && (
        <Badge variant="secondary" className="text-[10px]">закрываю…</Badge>
      )}
    </ScrollTab>
  )
}
