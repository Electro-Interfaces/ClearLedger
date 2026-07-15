/**
 * «Парк оборудования» — главная панель складского учёта оборудования ЭЗС
 * (раздел «Управленческий» → группа «Оборудование», профиль energy/РусГидро).
 *
 * Единица = станция-железка складского контура (серийник, вендор, модель,
 * состояние жизненного цикла). Карточки создаются при закупке/демонтаже/импорте
 * — НЕ для всего работающего парка, поэтому KPI «В эксплуатации» подписан
 * «прошедшие через склад». Матрица переходов живёт на бэке: сервер отдаёт
 * allowedOps[] в каждой единице, фронт просто рисует кнопки доступных операций.
 *
 * Состав: KPI-ряд · тулбар (поиск + фильтры + действия) · реестр единиц ·
 * карточка единицы (паспорт, операции, таймлайн движений) · формы создания /
 * демонтажа со станции / импорта из Excel. Все диалоги — в этом файле.
 */

import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import {
  ArrowDown, ArrowUp, ChevronsUpDown, Loader2, Pencil, Plus, Search,
  Trash2, Unplug, Upload,
} from 'lucide-react'
import { Kpi } from '@/components/workspace/analytics/Kpi'
import { ApiError } from '@/services/apiClient'
import { getLocations, loadLocations } from '@/services/locationService'
import type { ServiceLocation } from '@/types/location'
import {
  applyUnitMovement, createUnit, deleteUnit, dismantleFromSite,
  getEquipmentOverview, getUnit, importUnitsXlsx, listUnits, patchUnit,
  CUSTODIAN_LABELS, UNIT_OP_META, UNIT_STATE_META,
  type EquipmentUnit, type ImportReport, type MovementPayload,
  type UnitDetail, type UnitInPayload, type UnitOp, type UnitState,
} from '@/services/equipmentService'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

// ─── утилиты ────────────────────────────────────────────────────────────────

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.detail
  return e instanceof Error ? e.message : String(e)
}

/** Краткая дата (дд.мм.гг) из ISO-строки / даты YYYY-MM-DD. */
function fmtD(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(+d)) return iso
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}

/** «Где находится»: локация | держатель с меткой | «—». */
function placeLabel(u: EquipmentUnit): string {
  if (u.location) return u.location.name
  if (u.custodianName) {
    const cl = CUSTODIAN_LABELS[u.custodian]
    return cl && cl !== '—' ? `${cl}: ${u.custodianName}` : u.custodianName
  }
  const cl = CUSTODIAN_LABELS[u.custodian]
  return cl && cl !== '—' && u.custodian !== 'none' ? cl : '—'
}

function stateBadge(state: UnitState, label?: string) {
  const meta = UNIT_STATE_META[state]
  return (
    <Badge variant="outline" className={meta?.cls ?? ''}>
      {label || meta?.label || state}
    </Badge>
  )
}

/** Инвалидация всех витрин оборудования после мутаций. */
function invalidateEquipment(qc: QueryClient) {
  for (const key of ['eq-units', 'eq-unit', 'eq-overview', 'eq-movements', 'eq-warehouses']) {
    void qc.invalidateQueries({ queryKey: [key] })
  }
}

const ALL_STATES = Object.keys(UNIT_STATE_META) as UnitState[]

// ─── выбор локации (Select + опц. Input-фильтр — площадок ~600) ─────────────

function LocPicker({ items, value, onChange, placeholder, withFilter }: {
  items: ServiceLocation[]
  value: string
  onChange: (v: string) => void
  placeholder: string
  withFilter?: boolean
}) {
  const [flt, setFlt] = useState('')
  const shown = useMemo(() => {
    const f = flt.trim().toLowerCase()
    let list = f
      ? items.filter((l) => `${l.name} ${l.code} ${l.address ?? ''}`.toLowerCase().includes(f))
      : items
    list = list.slice(0, 300)
    if (value && !list.some((l) => l.id === value)) {
      const sel = items.find((l) => l.id === value)
      if (sel) list = [sel, ...list]
    }
    return list
  }, [items, flt, value])
  return (
    <div className="space-y-1.5">
      {withFilter && (
        <Input value={flt} onChange={(e) => setFlt(e.target.value)}
          placeholder="Фильтр по названию / коду…" className="h-8" />
      )}
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="w-full"><SelectValue placeholder={placeholder} /></SelectTrigger>
        <SelectContent>
          {shown.length === 0 && (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">Ничего не найдено</div>
          )}
          {shown.map((l) => (
            <SelectItem key={l.id} value={l.id}>
              {l.name}{l.address ? ` · ${l.address}` : ''}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

/** Ярлык + значение в паспорте (2-колоночная сетка). */
function KV({ label, value }: { label: string; value?: ReactNode }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{label}</div>
      <div className="text-sm break-words">{value ?? '—'}</div>
    </div>
  )
}

// ─── MovementDialog: динамическая форма операции по op ──────────────────────

function MovementDialog({ companyId, unit, op, warehouses, sites, onClose }: {
  companyId: string
  unit: EquipmentUnit
  op: UnitOp
  warehouses: ServiceLocation[]
  sites: ServiceLocation[]
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [occurredOn, setOccurredOn] = useState(todayISO())
  const [basis, setBasis] = useState('')
  const [comment, setComment] = useState('')
  const [toLocationId, setToLocationId] = useState('')
  const [reservedForId, setReservedForId] = useState('')
  const [counterparty, setCounterparty] = useState('')
  const [custodian, setCustodian] = useState<'contractor' | 'vendor'>('contractor')
  const [toState, setToState] = useState<UnitState | ''>('')
  const [syncPassport, setSyncPassport] = useState(false)

  const mut = useMutation({
    mutationFn: (body: MovementPayload) => applyUnitMovement(companyId, unit.id, body),
    onSuccess: () => {
      toast.success(`${UNIT_OP_META[op].label}: операция проведена`)
      invalidateEquipment(qc)
      onClose()
    },
    onError: (e) => toast.error('Операция не проведена', { description: errMsg(e) }),
  })

  function validate(): string | null {
    switch (op) {
      case 'transfer':
        if (!toLocationId) return 'Выберите склад-получатель'
        if (toLocationId === unit.location?.id) return 'Склад-получатель совпадает с текущим'
        return null
      case 'to_installation':
        return toLocationId ? null : 'Выберите площадку ЭЗС'
      case 'from_repair':
      case 'dismantle':
        return toLocationId ? null : 'Выберите склад-получатель'
      case 'to_repair':
      case 'to_vendor':
        return counterparty.trim() ? null : 'Укажите контрагента'
      case 'correction':
        if (!toState) return 'Выберите новое состояние'
        if (!comment.trim()) return 'Комментарий обязателен для корректировки'
        return null
      default:
        return null
    }
  }

  function submit() {
    const problem = validate()
    if (problem) { toast.error(problem); return }
    const body: MovementPayload = {
      op,
      occurredOn,
      basis: basis.trim() || undefined,
      comment: comment.trim() || undefined,
    }
    switch (op) {
      case 'transfer':
      case 'to_installation':
      case 'from_repair':
      case 'dismantle':
        body.toLocationId = toLocationId
        break
      case 'reserve':
        if (reservedForId) body.reservedForLocationId = reservedForId
        break
      case 'commissioning':
        body.syncPassport = syncPassport
        break
      case 'to_repair':
        body.custodian = custodian
        body.counterparty = counterparty.trim()
        break
      case 'to_vendor':
        body.counterparty = counterparty.trim()
        break
      case 'correction':
        body.toState = toState || undefined
        if (toLocationId) body.toLocationId = toLocationId
        break
      default:
        break
    }
    mut.mutate(body)
  }

  const allLocations = useMemo(() => [...warehouses, ...sites], [warehouses, sites])

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {UNIT_OP_META[op].label} — {unit.serialNumber ?? unit.model ?? 'единица'}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            Текущее: {stateBadge(unit.state, unit.stateLabel)}
            <span>· {placeLabel(unit)}</span>
          </div>

          {op === 'transfer' && (
            <div className="space-y-1.5">
              <Label>Склад-получатель</Label>
              <LocPicker items={warehouses.filter((w) => w.id !== unit.location?.id)}
                value={toLocationId} onChange={setToLocationId} placeholder="Выберите склад" />
            </div>
          )}

          {op === 'reserve' && (
            <div className="space-y-1.5">
              <Label>Резерв под площадку (необязательно)</Label>
              <LocPicker items={sites} value={reservedForId} onChange={setReservedForId}
                placeholder="Площадка ЭЗС" withFilter />
            </div>
          )}

          {op === 'to_installation' && (
            <div className="space-y-1.5">
              <Label>Площадка ЭЗС</Label>
              <LocPicker items={sites} value={toLocationId} onChange={setToLocationId}
                placeholder="Выберите площадку" withFilter />
            </div>
          )}

          {op === 'commissioning' && (
            <label className="flex cursor-pointer items-center gap-2.5 rounded-md border border-border/50 px-3 py-2 hover:bg-accent/30">
              <input type="checkbox" checked={syncPassport}
                onChange={(e) => setSyncPassport(e.target.checked)} className="size-4 accent-primary" />
              <div>
                <div className="text-sm font-medium">Обновить паспорт площадки из карточки</div>
                <div className="text-xs text-muted-foreground">Мощность, коннекторы, вендор/модель — в паспорт L2 площадки</div>
              </div>
            </label>
          )}

          {op === 'to_repair' && (
            <>
              <div className="space-y-1.5">
                <Label>Кто держит в ремонте</Label>
                <div className="flex gap-4">
                  {([['contractor', 'Подрядчик'], ['vendor', 'Производитель']] as const).map(([v, l]) => (
                    <label key={v} className="flex cursor-pointer items-center gap-2 text-sm">
                      <input type="radio" name="eq-repair-custodian" value={v}
                        checked={custodian === v} onChange={() => setCustodian(v)}
                        className="size-4 accent-primary" />
                      {l}
                    </label>
                  ))}
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>Контрагент</Label>
                <Input value={counterparty} onChange={(e) => setCounterparty(e.target.value)}
                  placeholder="Название организации" />
              </div>
            </>
          )}

          {(op === 'from_repair' || op === 'dismantle') && (
            <div className="space-y-1.5">
              <Label>Склад-получатель</Label>
              <LocPicker items={warehouses} value={toLocationId} onChange={setToLocationId}
                placeholder="Выберите склад" />
            </div>
          )}

          {op === 'to_vendor' && (
            <div className="space-y-1.5">
              <Label>Контрагент (производитель)</Label>
              <Input value={counterparty} onChange={(e) => setCounterparty(e.target.value)}
                placeholder="Название организации" />
            </div>
          )}

          {op === 'correction' && (
            <>
              <div className="space-y-1.5">
                <Label>Новое состояние</Label>
                <Select value={toState} onValueChange={(v) => setToState(v as UnitState)}>
                  <SelectTrigger className="w-full"><SelectValue placeholder="Выберите состояние" /></SelectTrigger>
                  <SelectContent>
                    {ALL_STATES.map((s) => (
                      <SelectItem key={s} value={s}>{UNIT_STATE_META[s].label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Локация (необязательно)</Label>
                <LocPicker items={allLocations} value={toLocationId} onChange={setToLocationId}
                  placeholder="Склад или площадка" withFilter />
              </div>
            </>
          )}

          {/* Общие поля всех операций */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Дата операции</Label>
              <Input type="date" value={occurredOn} onChange={(e) => setOccurredOn(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Основание</Label>
              <Input value={basis} onChange={(e) => setBasis(e.target.value)}
                placeholder="№ накладной, приказа…" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Комментарий{op === 'correction' ? ' (обязателен)' : ''}</Label>
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button onClick={submit} disabled={mut.isPending}>
            {mut.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Провести
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── UnitDetailsDialog: паспорт + операции + таймлайн движений ──────────────

interface EditState {
  serialNumber: string; vendor: string; model: string; stationType: string
  powerKwt: string; connectorsCount: string; connectorTypes: string
  inventoryNumber: string; supplier: string; purchaseDoc: string
  purchaseDate: string; warrantyUntil: string; isUsed: boolean; notes: string
}

function toEditState(u: UnitDetail): EditState {
  return {
    serialNumber: u.serialNumber ?? '', vendor: u.vendor ?? '', model: u.model ?? '',
    stationType: u.stationType ?? '', powerKwt: u.powerKwt != null ? String(u.powerKwt) : '',
    connectorsCount: u.connectorsCount != null ? String(u.connectorsCount) : '',
    connectorTypes: u.connectorTypes ?? '', inventoryNumber: u.inventoryNumber ?? '',
    supplier: u.supplier ?? '', purchaseDoc: u.purchaseDoc ?? '',
    purchaseDate: u.purchaseDate ?? '', warrantyUntil: u.warrantyUntil ?? '',
    isUsed: u.isUsed, notes: u.notes ?? '',
  }
}

const sOrNull = (v: string): string | null => v.trim() || null
function numOrNull(v: string): number | null {
  if (!v.trim()) return null
  const n = Number(v.replace(',', '.'))
  return Number.isFinite(n) ? n : null
}

function editToPayload(e: EditState): Partial<UnitInPayload> {
  return {
    serialNumber: sOrNull(e.serialNumber), vendor: sOrNull(e.vendor), model: sOrNull(e.model),
    stationType: sOrNull(e.stationType), powerKwt: numOrNull(e.powerKwt),
    connectorsCount: numOrNull(e.connectorsCount), connectorTypes: sOrNull(e.connectorTypes),
    inventoryNumber: sOrNull(e.inventoryNumber), supplier: sOrNull(e.supplier),
    purchaseDoc: sOrNull(e.purchaseDoc), purchaseDate: e.purchaseDate || null,
    warrantyUntil: e.warrantyUntil || null, isUsed: e.isUsed, notes: sOrNull(e.notes),
  }
}

/** Поле паспорта в режиме редактирования. */
function EF({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      {children}
    </div>
  )
}

function UnitDetailsDialog({ companyId, unitId, warehouses, sites, onClose }: {
  companyId: string
  unitId: string
  warehouses: ServiceLocation[]
  sites: ServiceLocation[]
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [edit, setEdit] = useState<EditState | null>(null)
  const [movementOp, setMovementOp] = useState<UnitOp | null>(null)
  const [confirmDel, setConfirmDel] = useState(false)

  const detQ = useQuery({
    queryKey: ['eq-unit', companyId, unitId],
    queryFn: () => getUnit(companyId, unitId),
  })
  const unit = detQ.data

  const patchMut = useMutation({
    mutationFn: (body: Partial<UnitInPayload>) => patchUnit(companyId, unitId, body),
    onSuccess: () => {
      toast.success('Паспорт единицы обновлён')
      setEdit(null)
      invalidateEquipment(qc)
    },
    onError: (e) => toast.error('Не удалось сохранить паспорт', { description: errMsg(e) }),
  })

  const delMut = useMutation({
    mutationFn: () => deleteUnit(companyId, unitId),
    onSuccess: () => {
      toast.success('Карточка единицы удалена')
      invalidateEquipment(qc)
      onClose()
    },
    onError: (e) => toast.error('Удаление невозможно', { description: errMsg(e) }),
  })

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            Единица {unit?.serialNumber ?? unit?.inventoryNumber ?? ''}
            {unit && stateBadge(unit.state, unit.stateLabel)}
          </DialogTitle>
        </DialogHeader>

        {detQ.isLoading && (
          <div className="flex justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}
        {detQ.isError && (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Не удалось загрузить карточку: {errMsg(detQ.error)}
          </div>
        )}

        {unit && (
          <div className="space-y-5">
            {/* Паспорт: просмотр или редактирование */}
            {edit ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <EF label="Серийный №">
                    <Input value={edit.serialNumber} onChange={(e) => setEdit({ ...edit, serialNumber: e.target.value })} />
                  </EF>
                  <EF label="Вендор">
                    <Input value={edit.vendor} onChange={(e) => setEdit({ ...edit, vendor: e.target.value })} />
                  </EF>
                  <EF label="Модель">
                    <Input value={edit.model} onChange={(e) => setEdit({ ...edit, model: e.target.value })} />
                  </EF>
                  <EF label="Тип (DC/AC)">
                    <Input value={edit.stationType} onChange={(e) => setEdit({ ...edit, stationType: e.target.value })} placeholder="DC" />
                  </EF>
                  <EF label="Мощность, кВт">
                    <Input type="number" value={edit.powerKwt} onChange={(e) => setEdit({ ...edit, powerKwt: e.target.value })} />
                  </EF>
                  <EF label="Коннекторов">
                    <Input type="number" value={edit.connectorsCount} onChange={(e) => setEdit({ ...edit, connectorsCount: e.target.value })} />
                  </EF>
                  <EF label="Типы коннекторов">
                    <Input value={edit.connectorTypes} onChange={(e) => setEdit({ ...edit, connectorTypes: e.target.value })} placeholder="CCS2, CHAdeMO" />
                  </EF>
                  <EF label="Инв. №">
                    <Input value={edit.inventoryNumber} onChange={(e) => setEdit({ ...edit, inventoryNumber: e.target.value })} />
                  </EF>
                  <EF label="Поставщик">
                    <Input value={edit.supplier} onChange={(e) => setEdit({ ...edit, supplier: e.target.value })} />
                  </EF>
                  <EF label="Документ закупки">
                    <Input value={edit.purchaseDoc} onChange={(e) => setEdit({ ...edit, purchaseDoc: e.target.value })} />
                  </EF>
                  <EF label="Дата закупки">
                    <Input type="date" value={edit.purchaseDate} onChange={(e) => setEdit({ ...edit, purchaseDate: e.target.value })} />
                  </EF>
                  <EF label="Гарантия до">
                    <Input type="date" value={edit.warrantyUntil} onChange={(e) => setEdit({ ...edit, warrantyUntil: e.target.value })} />
                  </EF>
                </div>
                <label className="flex w-fit cursor-pointer items-center gap-2 text-sm">
                  <input type="checkbox" checked={edit.isUsed}
                    onChange={(e) => setEdit({ ...edit, isUsed: e.target.checked })} className="size-4 accent-primary" />
                  Б/у (бывшая в эксплуатации)
                </label>
                <EF label="Заметки">
                  <Textarea value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} rows={2} />
                </EF>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" size="sm" onClick={() => setEdit(null)}>Отмена</Button>
                  <Button size="sm" onClick={() => patchMut.mutate(editToPayload(edit))} disabled={patchMut.isPending}>
                    {patchMut.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                    Сохранить паспорт
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                  <KV label="Серийный №" value={unit.serialNumber ?? undefined} />
                  <KV label="Инв. №" value={unit.inventoryNumber ?? undefined} />
                  <KV label="Вендор" value={unit.vendor ?? unit.vendorRaw ?? undefined} />
                  <KV label="Модель" value={unit.model ?? undefined} />
                  <KV label="Тип станции" value={unit.stationType ?? undefined} />
                  <KV label="Мощность" value={unit.powerKwt != null ? `${nf0.format(unit.powerKwt)} кВт` : undefined} />
                  <KV label="Коннекторы"
                    value={unit.connectorsCount != null || unit.connectorTypes
                      ? `${unit.connectorsCount ?? '—'}${unit.connectorTypes ? ` · ${unit.connectorTypes}` : ''}`
                      : undefined} />
                  <KV label="Б/у" value={unit.isUsed ? 'Да' : 'Нет'} />
                  <KV label="Поставщик" value={unit.supplier ?? undefined} />
                  <KV label="Документ закупки" value={unit.purchaseDoc ?? undefined} />
                  <KV label="Дата закупки" value={unit.purchaseDate ? fmtD(unit.purchaseDate) : undefined} />
                  <KV label="Гарантия до" value={unit.warrantyUntil ? fmtD(unit.warrantyUntil) : undefined} />
                  <KV label="Местонахождение" value={placeLabel(unit)} />
                  <KV label="Резерв под" value={unit.reservedFor?.name ?? undefined} />
                  <KV label="Склад происхождения" value={unit.originLocation?.name ?? undefined} />
                  <KV label="Заметки" value={unit.notes ?? undefined} />
                </div>

                {/* Операции жизненного цикла — только разрешённые сервером */}
                <div className="flex flex-wrap items-center gap-2 border-t border-border/50 pt-3">
                  {unit.allowedOps.map((op) => (
                    <Button key={op} variant="outline" size="sm" onClick={() => setMovementOp(op)}>
                      {UNIT_OP_META[op]?.label ?? op}
                    </Button>
                  ))}
                  {unit.allowedOps.length === 0 && (
                    <span className="text-xs text-muted-foreground">Операции недоступны (финальное состояние)</span>
                  )}
                  <Button variant="ghost" size="sm" className="ml-auto"
                    onClick={() => setEdit(toEditState(unit))}>
                    <Pencil className="h-3.5 w-3.5 mr-1.5" />
                    Редактировать паспорт
                  </Button>
                </div>
              </>
            )}

            {/* Таймлайн движений */}
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground/70">
                История движений · {unit.movements.length}
              </div>
              <div className="overflow-x-auto rounded-md border border-border/50">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b bg-muted/40 text-muted-foreground">
                      <th className="p-2 text-left font-medium whitespace-nowrap">Дата</th>
                      <th className="p-2 text-left font-medium whitespace-nowrap">Операция</th>
                      <th className="p-2 text-left font-medium">Откуда → Куда</th>
                      <th className="p-2 text-left font-medium">Состояние</th>
                      <th className="p-2 text-left font-medium">Контрагент</th>
                      <th className="p-2 text-left font-medium">Основание</th>
                      <th className="p-2 text-left font-medium whitespace-nowrap">Кто</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unit.movements.length === 0 && (
                      <tr><td colSpan={7} className="p-4 text-center text-muted-foreground">Движений пока нет</td></tr>
                    )}
                    {unit.movements.map((m) => (
                      <tr key={m.id} className="border-b border-border/30">
                        <td className="p-2 whitespace-nowrap font-mono">{fmtD(m.occurredOn)}</td>
                        <td className="p-2 whitespace-nowrap">{m.opLabel || UNIT_OP_META[m.op]?.label || m.op}</td>
                        <td className="p-2">{m.fromLocation?.name ?? '—'} → {m.toLocation?.name ?? '—'}</td>
                        <td className="p-2 text-muted-foreground">
                          {(m.fromStateLabel ?? '—')} → {(m.toStateLabel ?? '—')}
                        </td>
                        <td className="p-2">{m.counterparty ?? '—'}</td>
                        <td className="p-2">{m.basis ?? '—'}</td>
                        <td className="p-2 text-muted-foreground">{m.createdBy ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Удаление карточки (бэкенд вернёт 409 при движениях >1) */}
            <div className="flex items-center justify-between border-t border-border/50 pt-3">
              <Button variant="ghost" size="sm"
                className="text-muted-foreground hover:text-destructive"
                disabled={delMut.isPending}
                onClick={() => (confirmDel ? delMut.mutate() : setConfirmDel(true))}>
                <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                {confirmDel ? 'Точно удалить карточку?' : 'Удалить карточку'}
              </Button>
              <div className="text-[11px] text-muted-foreground">
                Создана {fmtD(unit.createdAt)} · обновлена {fmtD(unit.updatedAt)}
              </div>
            </div>
          </div>
        )}

        {unit && movementOp && (
          <MovementDialog companyId={companyId} unit={unit} op={movementOp}
            warehouses={warehouses} sites={sites} onClose={() => setMovementOp(null)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

// ─── UnitFormDialog: создание единицы (поступление на склад) ────────────────

function UnitFormDialog({ companyId, warehouses, onClose }: {
  companyId: string
  warehouses: ServiceLocation[]
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [serial, setSerial] = useState('')
  const [vendor, setVendor] = useState('')
  const [model, setModel] = useState('')
  const [stype, setStype] = useState('')
  const [power, setPower] = useState('')
  const [connCount, setConnCount] = useState('')
  const [connTypes, setConnTypes] = useState('')
  const [inv, setInv] = useState('')
  const [supplier, setSupplier] = useState('')
  const [pdoc, setPdoc] = useState('')
  const [pdate, setPdate] = useState('')
  const [wdate, setWdate] = useState('')
  const [isUsed, setIsUsed] = useState(false)
  const [warehouseId, setWarehouseId] = useState('')
  const [occurredOn, setOccurredOn] = useState(todayISO())
  const [basis, setBasis] = useState('')
  const [notes, setNotes] = useState('')

  const mut = useMutation({
    mutationFn: (body: UnitInPayload) => createUnit(companyId, body),
    onSuccess: (u) => {
      toast.success(`Единица создана${u.serialNumber ? `: ${u.serialNumber}` : ''}`)
      invalidateEquipment(qc)
      onClose()
    },
    onError: (e) => toast.error('Не удалось создать единицу', { description: errMsg(e) }),
  })

  function submit() {
    if (!warehouseId) { toast.error('Выберите склад поступления'); return }
    mut.mutate({
      serialNumber: sOrNull(serial), vendor: sOrNull(vendor), model: sOrNull(model),
      stationType: sOrNull(stype), powerKwt: numOrNull(power),
      connectorsCount: numOrNull(connCount), connectorTypes: sOrNull(connTypes),
      inventoryNumber: sOrNull(inv), supplier: sOrNull(supplier), purchaseDoc: sOrNull(pdoc),
      purchaseDate: pdate || null, warrantyUntil: wdate || null,
      isUsed, notes: sOrNull(notes),
      initialLocationId: warehouseId,
      occurredOn: occurredOn || undefined,
      basis: basis.trim() || undefined,
    })
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Новая единица оборудования</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-1">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <EF label="Серийный №">
              <Input value={serial} onChange={(e) => setSerial(e.target.value)} placeholder="SN-…" />
            </EF>
            <EF label="Вендор">
              <Input value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="Sitronics" />
            </EF>
            <EF label="Модель">
              <Input value={model} onChange={(e) => setModel(e.target.value)} />
            </EF>
            <EF label="Тип (DC/AC)">
              <Input value={stype} onChange={(e) => setStype(e.target.value)} placeholder="DC" />
            </EF>
            <EF label="Мощность, кВт">
              <Input type="number" value={power} onChange={(e) => setPower(e.target.value)} placeholder="150" />
            </EF>
            <EF label="Коннекторов">
              <Input type="number" value={connCount} onChange={(e) => setConnCount(e.target.value)} placeholder="2" />
            </EF>
            <EF label="Типы коннекторов">
              <Input value={connTypes} onChange={(e) => setConnTypes(e.target.value)} placeholder="CCS2, CHAdeMO" />
            </EF>
            <EF label="Инв. №">
              <Input value={inv} onChange={(e) => setInv(e.target.value)} />
            </EF>
            <EF label="Поставщик">
              <Input value={supplier} onChange={(e) => setSupplier(e.target.value)} />
            </EF>
            <EF label="Документ закупки">
              <Input value={pdoc} onChange={(e) => setPdoc(e.target.value)} placeholder="ТН №…" />
            </EF>
            <EF label="Дата закупки">
              <Input type="date" value={pdate} onChange={(e) => setPdate(e.target.value)} />
            </EF>
            <EF label="Гарантия до">
              <Input type="date" value={wdate} onChange={(e) => setWdate(e.target.value)} />
            </EF>
          </div>

          <label className="flex w-fit cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={isUsed} onChange={(e) => setIsUsed(e.target.checked)}
              className="size-4 accent-primary" />
            Б/у (бывшая в эксплуатации)
          </label>

          <div className="grid grid-cols-2 gap-3 border-t border-border/50 pt-3">
            <div className="space-y-1.5 col-span-2 sm:col-span-1">
              <Label>Склад поступления</Label>
              <LocPicker items={warehouses} value={warehouseId} onChange={setWarehouseId}
                placeholder="Выберите склад" />
              {warehouses.length === 0 && (
                <div className="text-xs text-amber-600 dark:text-amber-400">
                  Складов нет — создайте объект типа «Склад» в разделе «Объекты»
                </div>
              )}
            </div>
            <div className="space-y-1.5">
              <Label>Дата операции</Label>
              <Input type="date" value={occurredOn} onChange={(e) => setOccurredOn(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Основание</Label>
            <Input value={basis} onChange={(e) => setBasis(e.target.value)} placeholder="№ накладной, договора…" />
          </div>
          <div className="space-y-1.5">
            <Label>Заметки</Label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button onClick={submit} disabled={mut.isPending}>
            {mut.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Создать
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── DismantleDialog: демонтаж со станции (карточка из паспорта площадки) ───

function DismantleDialog({ companyId, warehouses, sites, onClose }: {
  companyId: string
  warehouses: ServiceLocation[]
  sites: ServiceLocation[]
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [siteId, setSiteId] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [occurredOn, setOccurredOn] = useState(todayISO())
  const [basis, setBasis] = useState('')
  const [comment, setComment] = useState('')
  const [setDecommissioned, setSetDecommissioned] = useState(false)

  const mut = useMutation({
    mutationFn: () => dismantleFromSite(companyId, {
      siteLocationId: siteId,
      warehouseId,
      occurredOn: occurredOn || undefined,
      basis: basis.trim() || undefined,
      comment: comment.trim() || undefined,
      setDecommissioned,
    }),
    onSuccess: (res) => {
      toast.success('Демонтаж проведён', {
        description: res.unitCreated ? 'Карточка создана из паспорта площадки' : undefined,
      })
      invalidateEquipment(qc)
      void qc.invalidateQueries({ queryKey: ['eq-locations'] })
      onClose()
    },
    onError: (e) => toast.error('Демонтаж не проведён', { description: errMsg(e) }),
  })

  function submit() {
    if (!siteId) { toast.error('Выберите площадку ЭЗС'); return }
    if (!warehouseId) { toast.error('Выберите склад-приёмник'); return }
    mut.mutate()
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Демонтаж со станции</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-1">
          <p className="text-xs text-muted-foreground">
            Если у станции ещё нет карточки в складском контуре — она будет создана
            автоматически из паспорта площадки.
          </p>
          <div className="space-y-1.5">
            <Label>Площадка ЭЗС</Label>
            <LocPicker items={sites} value={siteId} onChange={setSiteId}
              placeholder="Выберите площадку" withFilter />
          </div>
          <div className="space-y-1.5">
            <Label>Склад-приёмник</Label>
            <LocPicker items={warehouses} value={warehouseId} onChange={setWarehouseId}
              placeholder="Выберите склад" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Дата операции</Label>
              <Input type="date" value={occurredOn} onChange={(e) => setOccurredOn(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Основание</Label>
              <Input value={basis} onChange={(e) => setBasis(e.target.value)} placeholder="Приказ, акт…" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Комментарий</Label>
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} />
          </div>
          <label className="flex cursor-pointer items-center gap-2.5 rounded-md border border-border/50 px-3 py-2 hover:bg-accent/30">
            <input type="checkbox" checked={setDecommissioned}
              onChange={(e) => setSetDecommissioned(e.target.checked)} className="size-4 accent-primary" />
            <div>
              <div className="text-sm font-medium">Отметить площадку выведенной из эксплуатации</div>
              <div className="text-xs text-muted-foreground">Статус площадки в справочнике объектов будет обновлён</div>
            </div>
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button onClick={submit} disabled={mut.isPending}>
            {mut.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Провести демонтаж
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── ImportDialog: импорт реестра единиц из Excel (dry-run → импорт) ────────

function ImportReportView({ report }: { report: ImportReport }) {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <Badge variant="outline" className={report.dryRun
          ? 'border-blue-400/50 text-blue-600 dark:text-blue-300/80'
          : 'border-emerald-400/50 text-emerald-600 dark:text-emerald-300/80'}>
          {report.dryRun ? 'Проверка (dry-run)' : 'Импорт выполнен'}
        </Badge>
        <span>Создано: <b className="tabular-nums">{nf0.format(report.created)}</b></span>
        <span>Обновлено: <b className="tabular-nums">{nf0.format(report.updated)}</b></span>
        <span>Пропущено: <b className="tabular-nums">{nf0.format(report.skipped)}</b></span>
      </div>

      {report.warehousesCreated.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">
            {report.dryRun ? 'Будут созданы склады:' : 'Созданы склады:'}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {report.warehousesCreated.map((w) => (
              <Badge key={w} variant="outline">{w}</Badge>
            ))}
          </div>
        </div>
      )}

      {report.stateUnknown.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">
            Нераспознанные состояния (единицы получат состояние по умолчанию):
          </div>
          <div className="max-h-40 overflow-y-auto rounded-md border border-border/50">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <th className="p-1.5 text-left font-medium">Строка</th>
                  <th className="p-1.5 text-left font-medium">Значение</th>
                </tr>
              </thead>
              <tbody>
                {report.stateUnknown.map((s, i) => (
                  <tr key={i} className="border-b border-border/30">
                    <td className="p-1.5 font-mono">{s.row}</td>
                    <td className="p-1.5">{s.value ?? '(пусто)'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {report.errors.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-red-500/80">Ошибки ({report.errors.length}):</div>
          <div className="max-h-40 space-y-0.5 overflow-y-auto text-xs">
            {report.errors.map((e, i) => (
              <div key={i} className="text-red-500/80">Строка {e.row}: {e.message}</div>
            ))}
          </div>
        </div>
      )}

      {report.unknownColumns.length > 0 && (
        <div className="text-xs text-muted-foreground">
          Нераспознанные колонки: {report.unknownColumns.join(', ')}
        </div>
      )}
    </div>
  )
}

function ImportDialog({ companyId, onClose }: { companyId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<ImportReport | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(dryRun: boolean) {
    if (!file) { toast.error('Выберите файл .xlsx'); return }
    setBusy(true)
    try {
      const rep = await importUnitsXlsx(companyId, file, dryRun)
      setReport(rep)
      if (!dryRun) {
        invalidateEquipment(qc)
        void qc.invalidateQueries({ queryKey: ['eq-locations'] })
        toast.success(`Импорт завершён: создано ${rep.created}, обновлено ${rep.updated}`)
      }
    } catch (e) {
      toast.error(dryRun ? 'Проверка не удалась' : 'Импорт не удался', { description: errMsg(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Импорт единиц из Excel</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-1">
          <p className="text-xs text-muted-foreground">
            Реестр оборудования .xlsx: серийники, вендоры, модели, склады, состояния.
            Сначала выполните проверку (dry-run) — файл будет разобран без записи.
          </p>
          <Input type="file" accept=".xlsx"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(null) }} />
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => void run(true)} disabled={!file || busy}>
              {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Проверить (dry-run)
            </Button>
            <Button size="sm" onClick={() => void run(false)} disabled={!file || busy}>
              {busy && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Импортировать
            </Button>
          </div>
          {report && <ImportReportView report={report} />}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Закрыть</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── реестр: сортируемая шапка ──────────────────────────────────────────────

type SortKey =
  | 'serialNumber' | 'vendor' | 'model' | 'powerKwt' | 'state'
  | 'place' | 'inventoryNumber' | 'updatedAt'

function sortVal(u: EquipmentUnit, k: SortKey): string | number {
  switch (k) {
    case 'serialNumber': return u.serialNumber ?? ''
    case 'vendor': return u.vendor ?? u.vendorRaw ?? ''
    case 'model': return u.model ?? ''
    case 'powerKwt': return u.powerKwt ?? -1
    case 'state': return UNIT_STATE_META[u.state]?.label ?? u.state
    case 'place': return placeLabel(u)
    case 'inventoryNumber': return u.inventoryNumber ?? ''
    case 'updatedAt': return u.updatedAt ?? ''
  }
}

// ─── главная панель ─────────────────────────────────────────────────────────

export function EquipmentFleetPanel({ companyId }: { companyId: string }) {
  // Фильтры реестра (q применяется по Enter/кнопке)
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [state, setState] = useState('all')
  const [vendor, setVendor] = useState('all')
  const [warehouseFilter, setWarehouseFilter] = useState('all')

  // Диалоги
  const [detailsId, setDetailsId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [dismantleOpen, setDismantleOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  // Справочник локаций (гидрация из бэкенда; склады + площадки ЭЗС)
  const locQ = useQuery({
    queryKey: ['eq-locations', companyId],
    queryFn: () => loadLocations(companyId),
    staleTime: 60_000,
  })
  const locations = locQ.data ?? getLocations()
  const warehouses = useMemo(
    () => locations.filter((l) => l.type === 'warehouse'),
    [locations],
  )
  const sites = useMemo(
    () => locations.filter((l) => l.type === 'ev_charging'),
    [locations],
  )

  const overviewQ = useQuery({
    queryKey: ['eq-overview', companyId],
    queryFn: () => getEquipmentOverview(companyId),
  })
  const overview = overviewQ.data

  const unitsQ = useQuery({
    queryKey: ['eq-units', companyId, { state, vendor, warehouseFilter, q }],
    queryFn: () => listUnits({
      companyId,
      state: state === 'all' ? undefined : state,
      vendor: vendor === 'all' ? undefined : vendor,
      locationId: warehouseFilter === 'all' ? undefined : warehouseFilter,
      q: q || undefined,
    }),
  })

  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'updatedAt', dir: 'desc' })
  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' }))

  const rows = useMemo(() => {
    const items = unitsQ.data?.items ?? []
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...items].sort((a, b) => {
      const va = sortVal(a, sort.key)
      const vb = sortVal(b, sort.key)
      if (typeof va === 'number' && typeof vb === 'number') return dir * (va - vb)
      return dir * String(va).localeCompare(String(vb), 'ru')
    })
  }, [unitsQ.data, sort])

  const H = ({ k, children, right }: { k: SortKey; children: ReactNode; right?: boolean }) => {
    const active = sort.key === k
    const Ico = active ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
    return (
      <th aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
        className={`p-2 font-medium ${right ? 'text-right' : 'text-left'}`}>
        <button onClick={() => toggleSort(k)} title="Сортировать по столбцу"
          className={`group inline-flex items-center gap-1 cursor-pointer transition-colors hover:text-foreground ${right ? 'flex-row-reverse' : ''} ${active ? 'text-foreground' : ''}`}>
          <span className="whitespace-nowrap">{children}</span>
          <Ico className={`h-3 w-3 shrink-0 ${active ? 'text-primary opacity-100' : 'opacity-30 group-hover:opacity-70'}`} />
        </button>
      </th>
    )
  }

  const cs = (k: UnitState) => overview?.countsByState?.[k] ?? 0
  const kpiVal = (n: number) => (overviewQ.isLoading ? '—' : nf0.format(n))
  const filtersActive = q !== '' || state !== 'all' || vendor !== 'all' || warehouseFilter !== 'all'
  const total = unitsQ.data?.total ?? 0

  return (
    <div className="p-4 space-y-4">
      {/* KPI-ряд по состояниям жизненного цикла */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
        <Kpi label="На складах новые" value={kpiVal(cs('in_stock_new'))} />
        <Kpi label="На складах б/у" value={kpiVal(cs('in_stock_used'))} />
        <Kpi label="Резерв" value={kpiVal(cs('reserved'))} />
        <Kpi label="В монтаже" value={kpiVal(cs('in_installation'))} />
        <Kpi label="В эксплуатации" value={kpiVal(cs('in_operation'))} sub="прошедшие через склад" />
        <Kpi label="В ремонте" value={kpiVal(cs('in_repair'))}
          sub={`дольше 30 дн: ${overview ? nf0.format(overview.inRepairOver30d) : '—'}`}
          cls={overview && overview.inRepairOver30d > 0 ? 'text-amber-600 dark:text-amber-300/90' : undefined} />
        <Kpi label="Списано/возврат" value={kpiVal(cs('written_off') + cs('returned_to_vendor'))} />
      </div>

      {/* Тулбар: поиск + фильтры + действия */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Input value={qInput} onChange={(e) => setQInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') setQ(qInput.trim()) }}
            placeholder="Серийник, модель, инв. №…" className="h-8 w-[220px]" />
          <Button variant="outline" size="icon" className="h-8 w-8" title="Искать"
            onClick={() => setQ(qInput.trim())}>
            <Search className="h-4 w-4" />
          </Button>
        </div>

        <Select value={state} onValueChange={setState}>
          <SelectTrigger className="h-8 w-[190px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">Все состояния</SelectItem>
            {ALL_STATES.map((s) => (
              <SelectItem key={s} value={s} className="text-xs">{UNIT_STATE_META[s].label}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={vendor} onValueChange={setVendor}>
          <SelectTrigger className="h-8 w-[170px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">Все вендоры</SelectItem>
            {(overview?.countsByVendor ?? []).map((v) => (
              <SelectItem key={v.vendor} value={v.vendor} className="text-xs">
                {v.vendor} · {nf0.format(v.count)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={warehouseFilter} onValueChange={setWarehouseFilter}>
          <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">Все склады</SelectItem>
            {warehouses.map((w) => (
              <SelectItem key={w.id} value={w.id} className="text-xs">{w.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" className="h-8" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-1.5" />
            Добавить единицу
          </Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setDismantleOpen(true)}>
            <Unplug className="h-4 w-4 mr-1.5" />
            Демонтаж со станции
          </Button>
          <Button size="sm" variant="outline" className="h-8" onClick={() => setImportOpen(true)}>
            <Upload className="h-4 w-4 mr-1.5" />
            Импорт из Excel
          </Button>
        </div>
      </div>

      {/* Реестр единиц */}
      {unitsQ.isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : unitsQ.isError ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Не удалось загрузить реестр: {errMsg(unitsQ.error)}
          </CardContent>
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            {filtersActive
              ? 'Ничего не найдено по заданным фильтрам.'
              : 'Единиц оборудования пока нет — добавьте вручную, импортируйте реестр или проведите демонтаж со станции.'}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/40 text-muted-foreground">
                  <H k="serialNumber">Серийный №</H>
                  <H k="vendor">Вендор</H>
                  <H k="model">Модель</H>
                  <H k="powerKwt" right>кВт</H>
                  <H k="state">Состояние</H>
                  <H k="place">Местонахождение</H>
                  <H k="inventoryNumber">Инв. №</H>
                  <H k="updatedAt" right>Обновлено</H>
                </tr>
              </thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.id} onClick={() => setDetailsId(u.id)}
                    className="cursor-pointer border-b border-border/30 hover:bg-muted/30">
                    <td className="p-2 font-mono font-medium whitespace-nowrap">{u.serialNumber ?? '—'}</td>
                    <td className="p-2 whitespace-nowrap">{u.vendor ?? u.vendorRaw ?? '—'}</td>
                    <td className="p-2 max-w-[220px] truncate">{u.model ?? '—'}</td>
                    <td className="p-2 text-right font-mono">{u.powerKwt != null ? nf0.format(u.powerKwt) : '—'}</td>
                    <td className="p-2 whitespace-nowrap">{stateBadge(u.state, u.stateLabel)}</td>
                    <td className="p-2 max-w-[260px] truncate">{placeLabel(u)}</td>
                    <td className="p-2 font-mono whitespace-nowrap">{u.inventoryNumber ?? '—'}</td>
                    <td className="p-2 text-right font-mono text-muted-foreground whitespace-nowrap">{fmtD(u.updatedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {total > 0 && (
        <div className="text-[11px] text-muted-foreground">
          Единиц: {nf0.format(total)}{filtersActive ? ' (по текущему отбору)' : ''}
        </div>
      )}

      {/* Диалоги */}
      {detailsId && (
        <UnitDetailsDialog companyId={companyId} unitId={detailsId}
          warehouses={warehouses} sites={sites} onClose={() => setDetailsId(null)} />
      )}
      {createOpen && (
        <UnitFormDialog companyId={companyId} warehouses={warehouses}
          onClose={() => setCreateOpen(false)} />
      )}
      {dismantleOpen && (
        <DismantleDialog companyId={companyId} warehouses={warehouses} sites={sites}
          onClose={() => setDismantleOpen(false)} />
      )}
      {importOpen && (
        <ImportDialog companyId={companyId} onClose={() => setImportOpen(false)} />
      )}
    </div>
  )
}
