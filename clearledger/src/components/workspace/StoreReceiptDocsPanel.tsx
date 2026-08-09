/**
 * «Магазин» → Склад → Приёмка.
 *
 * Первый документ, который Ledger порождает сам, а не читает из 1С. Точек ввода
 * две и обе законны: здесь, в центре, товаровед заводит накладную поставщика
 * (дальше — из ЭДО), а на станции ту же приёмку делают физически, со сканером.
 * Документ при этом один — иначе накладная и фактическое поступление разъедутся.
 *
 * Логика повторяет ордерную схему 1С:Розница, к которой товаровед привык:
 * «к поступлению» — товар заявлен, но на складе его ещё нет; «принят» — посчитан
 * и оприходован. Пока документ не принят, остатки не двигаются.
 */
import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, Building2, Check, ChevronsUpDown, CircleCheck, FileText,
  Loader2, PackagePlus, Plus, ScanBarcode, Send, Trash2, Warehouse,
} from 'lucide-react'
import {
  getStoreReceipts, createStoreReceipt, updateStoreReceipt, setStoreReceiptStatus,
  getStoreStations, createStoreReceiptFromUPD, sendStoreReceiptToStation,
  recordStoreReceiptSignature, distributeStoreReceipt, scanStoreReceipt, getStoreReceipt,
  createStoreSupplierDraft,
  type StoreReceipt, type StoreReceiptLine, type StoreReceiptInput, type StoreReceiptJournalData,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { ApiError } from '@/services/apiClient'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Callout } from '@/components/ui/callout'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command'
import { parseReceiptScan, SCAN_TYPE_LABEL } from '@/lib/receiptScanner'
import { useContracts, useCounterparties, useOrganizations } from '@/hooks/useReferences'
import type { Contract, Counterparty, Organization } from '@/types'

const STATUS_LABEL: Record<string, string> = {
  draft: 'черновик',
  expected: 'к поступлению',
  accepted: 'принят',
  reversed: 'сторнирован',
}
const STATUS_STYLE: Record<string, string> = {
  draft: 'border-zinc-600 text-zinc-400',
  expected: 'border-amber-400/50 text-amber-300/80',
  accepted: 'border-emerald-400/50 text-emerald-300/80',
  reversed: 'border-red-400/50 text-red-300/80',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded border px-2 py-0.5 text-xs ${STATUS_STYLE[status] ?? ''}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

function money(v: number) {
  return v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function shortDate(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('ru-RU')
}

type ReceiptQueryKey = readonly ['store-receipts', string, string]

function apiStatus(error: unknown) {
  return error instanceof ApiError ? error.status : null
}

function mutationError(error: unknown, fallback: string) {
  if (apiStatus(error) === 409) return (error as Error).message || 'Документ уже изменён другим пользователем.'
  if (apiStatus(error) === 403) return 'У вас нет прав на изменение приёмок.'
  return (error as Error)?.message || fallback
}

function replaceCachedReceipt(
  current: StoreReceiptJournalData | undefined,
  receipt: StoreReceipt,
  prepend = false,
): StoreReceiptJournalData | undefined {
  if (!current) return current
  const index = current.receipts.findIndex((item) => item.id === receipt.id)
  if (index < 0) {
    return prepend
      ? { receipts: [receipt, ...current.receipts], total: current.total + 1 }
      : current
  }
  return {
    ...current,
    receipts: current.receipts.map((item) => (item.id === receipt.id ? receipt : item)),
  }
}

function counterpartySource(counterparty: Counterparty) {
  return counterparty.externalRef || counterparty.raw ? '1С' : 'Ledger'
}

function isSupplierContract(contract: Contract) {
  return (contract.kind ?? '')
    .toLocaleLowerCase('ru-RU')
    .replaceAll('ё', 'е')
    .replace(/[\s_-]/g, '') === 'споставщиком'
}

function contractMatchesCounterparty(contract: Contract, counterparty: Counterparty) {
  return contract.counterpartyId === counterparty.id
    || (!!counterparty.externalRef && contract.counterpartyId === counterparty.externalRef)
}

function SupplierPicker({
  supplierId, snapshot, counterparties, disabled, isLoading, error,
  draftStationId, receiptNumber, onChange,
}: {
  supplierId: string | null
  snapshot: string
  counterparties: Counterparty[]
  disabled: boolean
  isLoading: boolean
  error: unknown
  draftStationId: number | null
  receiptNumber: string
  onChange: (supplierId: string | null, snapshot: string) => void
}) {
  const draftLockRef = useRef(false)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(snapshot)
  const [draftName, setDraftName] = useState(snapshot)
  const [draftInn, setDraftInn] = useState('')
  const [draftKpp, setDraftKpp] = useState('')
  const [draftPending, setDraftPending] = useState(false)
  const draftInnDigits = draftInn.replace(/\D/g, '')
  const draftInnValid = draftInnDigits.length === 10 || draftInnDigits.length === 12
  const selected = counterparties.find((counterparty) => counterparty.id === supplierId)
  const draft = useMutation({
    mutationFn: () => createStoreSupplierDraft({
      station_id: draftStationId!,
      name: draftName.trim(),
      inn: draftInn.trim() || null,
      kpp: draftKpp.trim() || null,
      role: 'supplier',
      comment: `Черновик из приёмки ${receiptNumber}`,
    }),
    onSuccess: (created) => {
      onChange(null, created.name)
      setQuery(created.name)
      setDraftPending(true)
      setOpen(false)
    },
    onSettled: () => { draftLockRef.current = false },
  })

  const submitDraft = () => {
    if (draftLockRef.current || draft.isPending || !draftStationId || !draftName.trim() || !draftInnValid) return
    draftLockRef.current = true
    draft.mutate()
  }

  if (error) {
    return (
      <label className="text-xs text-muted-foreground">Поставщик
        <Input value={snapshot} disabled={disabled}
               onChange={(event) => onChange(null, event.target.value)} className="mt-1" />
        <span className="mt-1 block text-warning">
          Справочник недоступен — сохранится текстовый снимок{supplierId ? ', текущая ссылка не очищена до изменения поля' : ''}.
        </span>
      </label>
    )
  }

  return (
    <div className="space-y-1">
      <span className="text-xs text-muted-foreground">Поставщик</span>
      <Popover open={open} onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (nextOpen) {
          setQuery(snapshot)
          setDraftName(snapshot)
        }
      }}>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" role="combobox" aria-expanded={open}
                  disabled={disabled || isLoading} className="h-auto min-h-11 w-full justify-between whitespace-normal px-3 py-2 text-left">
            <span className="min-w-0">
              <span className="block truncate">{selected?.shortName || selected?.name || snapshot || 'Выберите поставщика'}</span>
              {selected ? (
                <span className="mt-0.5 block truncate text-xs font-normal text-muted-foreground">
                  ИНН {selected.inn || 'не указан'} · {counterpartySource(selected)}
                </span>
              ) : snapshot ? (
                <span className="mt-0.5 block truncate text-xs font-normal text-warning">
                  {draftPending ? 'черновик станции · ожидает признания' : supplierId ? 'ссылка не найдена · снимок сохранён' : 'только текстовый снимок'}
                </span>
              ) : null}
            </span>
            {isLoading ? <Loader2 className="size-4 animate-spin" /> : <ChevronsUpDown className="size-4 opacity-50" />}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[min(94vw,520px)] p-0" align="start">
          <Command shouldFilter>
            <CommandInput value={query} onValueChange={(value) => {
              setQuery(value)
              setDraftName(value)
            }} placeholder="Поиск по наименованию или ИНН…" />
            <CommandList>
              <CommandEmpty>Совпадений в справочнике нет.</CommandEmpty>
              <CommandGroup heading="Контрагенты">
                {counterparties.map((counterparty) => (
                  <CommandItem key={counterparty.id}
                               value={`${counterparty.name} ${counterparty.shortName ?? ''} ${counterparty.inn} ${counterparty.kpp ?? ''}`}
                               onSelect={() => {
                                 onChange(counterparty.id, counterparty.shortName || counterparty.name)
                                 setDraftPending(false)
                                 setOpen(false)
                               }}>
                    <Building2 className="size-4" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{counterparty.shortName || counterparty.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        ИНН {counterparty.inn || 'не указан'}{counterparty.kpp ? ` · КПП ${counterparty.kpp}` : ''}
                      </span>
                    </span>
                    <span className="flex shrink-0 gap-1">
                      <Badge variant="outline">{counterpartySource(counterparty)}</Badge>
                      <Badge variant={counterparty.inn ? 'secondary' : 'destructive'}>
                        {counterparty.inn ? 'реквизиты' : 'без ИНН'}
                      </Badge>
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
              {query.trim() ? (
                <CommandGroup heading="Совместимый ввод">
                  <CommandItem value={`__snapshot__ ${query}`} onSelect={() => {
                    onChange(null, query.trim())
                    setDraftPending(false)
                    setOpen(false)
                  }}>
                    <FileText className="size-4" />
                    Использовать «{query.trim()}» как текстовый снимок
                  </CommandItem>
                </CommandGroup>
              ) : null}
            </CommandList>
          </Command>
          <div className="space-y-2 border-t border-border p-3">
            <div>
              <p className="text-xs font-medium">Новый поставщик на станции</p>
              <p className="text-xs text-muted-foreground">Создаётся черновик, не каноническая карточка сети.</p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Input value={draftName} onChange={(event) => setDraftName(event.target.value)}
                     disabled={!draftStationId || draft.isPending} placeholder="Наименование" className="sm:col-span-2" />
              <Input value={draftInn} onChange={(event) => setDraftInn(event.target.value)}
                     disabled={!draftStationId || draft.isPending} placeholder="ИНН" inputMode="numeric" />
              <Input value={draftKpp} onChange={(event) => setDraftKpp(event.target.value)}
                     disabled={!draftStationId || draft.isPending} placeholder="КПП" inputMode="numeric" />
            </div>
            {!draftStationId ? (
              <p className="text-xs text-warning">Для черновика сузьте область до одной станции.</p>
            ) : null}
            {draftInn && !draftInnValid ? (
              <p className="text-xs text-warning">ИНН должен содержать 10 или 12 цифр.</p>
            ) : null}
            {draft.isError ? (
              <p className="text-xs text-destructive" role="alert">
                {mutationError(draft.error, 'Черновик не создан. Можно сохранить поставщика текстом.')}
              </p>
            ) : null}
            <Button type="button" size="sm" variant="outline"
                    disabled={!draftStationId || !draftName.trim() || !draftInnValid || draft.isPending}
                    onClick={submitDraft}>
              {draft.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
              {draft.isPending ? 'Создаём…' : draft.isError ? 'Повторить' : 'Создать черновик'}
            </Button>
          </div>
        </PopoverContent>
      </Popover>
      {draftPending ? (
        <p className="text-xs text-warning" role="status" aria-live="polite">
          Черновик поставщика ожидает подтверждения центром. Приёмку можно сохранить, но нельзя провести или отправить.
        </p>
      ) : null}
    </div>
  )
}

function ContractPicker({
  contractId, snapshot, supplier, contracts, organizations, disabled, isLoading, error,
  organizationError, onChange,
}: {
  contractId: string | null
  snapshot: string
  supplier: Counterparty | undefined
  contracts: Contract[]
  organizations: Organization[]
  disabled: boolean
  isLoading: boolean
  error: unknown
  organizationError: unknown
  onChange: (contractId: string | null, snapshot: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(snapshot)
  const selected = contracts.find((contract) => contract.id === contractId)
  const organizationsById = useMemo(() => {
    const result = new Map<string, Organization>()
    for (const organization of organizations) {
      result.set(organization.id, organization)
      if (organization.externalRef) result.set(organization.externalRef, organization)
    }
    return result
  }, [organizations])
  const eligible = useMemo(
    () => supplier
      ? contracts.filter((contract) => contractMatchesCounterparty(contract, supplier) && isSupplierContract(contract))
      : [],
    [contracts, supplier],
  )
  const selectedEligible = !!selected && eligible.some((contract) => contract.id === selected.id)

  if (isLoading && !supplier) {
    return (
      <div className="space-y-1">
        <span className="text-xs text-muted-foreground">Договор</span>
        <Button type="button" variant="outline" disabled className="w-full justify-start">
          <Loader2 className="animate-spin" />Загрузка договоров…
        </Button>
      </div>
    )
  }

  if (error || !supplier) {
    return (
      <label className="text-xs text-muted-foreground">Договор
        <Input value={snapshot} disabled={disabled}
               onChange={(event) => onChange(null, event.target.value)} className="mt-1" />
        <span className={`mt-1 block ${error ? 'text-warning' : 'text-muted-foreground'}`}>
          {error
            ? `Справочник договоров недоступен — сохраняется текстовый снимок${contractId ? ', ссылка сохранена до изменения поля' : ''}.`
            : 'Связанный договор выбирается после поставщика; текст можно сохранить без ссылки.'}
        </span>
      </label>
    )
  }

  return (
    <div className="space-y-1">
      <span className="text-xs text-muted-foreground">Договор</span>
      <Popover open={open} onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (nextOpen) setQuery(snapshot)
      }}>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" role="combobox" aria-expanded={open}
                  disabled={disabled || isLoading} className="h-auto min-h-11 w-full justify-between whitespace-normal px-3 py-2 text-left">
            <span className="min-w-0">
              <span className="block truncate">{selected?.number || snapshot || 'Выберите договор с поставщиком'}</span>
              {selected ? (
                <span className={`mt-0.5 block truncate text-xs font-normal ${selectedEligible ? 'text-muted-foreground' : 'text-warning'}`}>
                  {selected.kind || 'вид не указан'} · {selected.externalRef ? '1С' : 'Ledger'}
                </span>
              ) : snapshot ? (
                <span className="mt-0.5 block truncate text-xs font-normal text-warning">
                  {contractId ? 'ссылка не найдена · снимок сохранён' : 'только текстовый снимок'}
                </span>
              ) : null}
            </span>
            {isLoading ? <Loader2 className="size-4 animate-spin" /> : <ChevronsUpDown className="size-4 opacity-50" />}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[min(94vw,560px)] p-0" align="start">
          <Command shouldFilter>
            <CommandInput value={query} onValueChange={setQuery} placeholder="Поиск по номеру договора…" />
            <CommandList>
              <CommandEmpty>Договоров вида «С поставщиком» не найдено.</CommandEmpty>
              <CommandGroup heading={`Договоры: ${supplier.shortName || supplier.name}`}>
                {eligible.map((contract) => {
                  const organization = organizationsById.get(contract.organizationId)
                  return (
                    <CommandItem key={contract.id}
                                 value={`${contract.number} ${contract.date} ${contract.kind ?? ''} ${organization?.name ?? ''}`}
                                 disabled={!organization}
                                 onSelect={() => {
                                   onChange(contract.id, contract.number)
                                   setOpen(false)
                                 }}>
                      <FileText className="size-4" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">№ {contract.number} от {shortDate(contract.date)}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {organization
                            ? `${organization.name} · в приёмке организация не закреплена`
                            : 'Организация договора не сопоставлена · выбрать нельзя'}
                        </span>
                      </span>
                      <span className="flex shrink-0 gap-1">
                        <Badge variant={organization ? 'outline' : 'destructive'}>
                          {organization ? 'организация' : 'без организации'}
                        </Badge>
                        <Badge variant={contract.isClosed ? 'destructive' : 'secondary'}>
                          {contract.isClosed ? 'закрыт' : contract.externalRef ? '1С' : 'Ledger'}
                        </Badge>
                      </span>
                    </CommandItem>
                  )
                })}
              </CommandGroup>
              {query.trim() ? (
                <CommandGroup heading="Совместимый ввод">
                  <CommandItem value={`__contract_snapshot__ ${query}`} onSelect={() => {
                    onChange(null, query.trim())
                    setOpen(false)
                  }}>
                    <FileText className="size-4" />
                    Использовать «{query.trim()}» как текстовый снимок
                  </CommandItem>
                </CommandGroup>
              ) : null}
            </CommandList>
          </Command>
          <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
            Показаны только договоры выбранного поставщика с видом «С поставщиком».
            Организация документа пока не хранится, поэтому она показана справочно и не угадывается автоматически.
          </p>
        </PopoverContent>
      </Popover>
      {selected && !selectedEligible ? (
        <p className="text-xs text-warning">Текущая ссылка не соответствует выбранному поставщику или виду договора. Выберите договор заново.</p>
      ) : null}
      {organizationError ? (
        <p className="text-xs text-warning">Справочник организаций недоступен: договор нельзя сопоставить и выбрать без догадки.</p>
      ) : null}
    </div>
  )
}

/** Пустая строка документа: заявленное и фактическое ведутся раздельно. */
const emptyLine = (): StoreReceiptLine => ({
  nomenclature_ref: null, name: '', barcode: null,
  qty_expected: 0, qty_fact: 0, price: 0, vat_rate: null, amount: 0,
  upd_codes: [], mark_codes: [], pack_codes: [], requires_mark: false, no_card: false,
})

export function StoreReceiptDocsPanel({ stations }: { stations?: string[] }) {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [openId, setOpenId] = useState<string | null>(null)
  const [onlyDiff, setOnlyDiff] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)

  const stationQuery = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
  })
  const requestedStationIds = useMemo(
    () => [...new Set((stations ?? [])
      .map(Number)
      .filter((stationId) => Number.isFinite(stationId) && stationId > 0))]
      .sort((left, right) => left - right),
    [stations],
  )
  const stationIds = useMemo(() => {
    const permitted = (stationQuery.data?.stations ?? []).map((station) => station.station_id)
    if (requestedStationIds.length === 0) return permitted
    const permittedSet = new Set(permitted)
    return requestedStationIds.filter((stationId) => permittedSet.has(stationId))
  }, [requestedStationIds, stationQuery.data])
  const scopeKey = stationIds.join(',')
  const receiptsQueryKey: ReceiptQueryKey = ['store-receipts', company.id, scopeKey]
  const receiptsQuery = useQuery({
    queryKey: receiptsQueryKey,
    queryFn: () => getStoreReceipts({ stationIds }),
    enabled: stationQuery.isSuccess && stationIds.length > 0,
  })
  const stationId = stationIds.length === 1 ? stationIds[0] : undefined
  const data = receiptsQuery.data

  const cacheReceipt = (receipt: StoreReceipt, prepend = false) => {
    qc.setQueryData<StoreReceiptJournalData>(
      receiptsQueryKey,
      (current) => replaceCachedReceipt(current, receipt, prepend),
    )
  }
  const open = useMemo(
    () => data?.receipts.find((r) => r.id === openId) ?? null,
    [data, openId],
  )

  if (stationQuery.isLoading || (receiptsQuery.isLoading && stationIds.length > 0)) {
    return <div className="p-6 text-sm text-muted-foreground" aria-live="polite">Загрузка приёмок…</div>
  }
  const queryError = stationQuery.error ?? receiptsQuery.error
  if (queryError) {
    const forbidden = apiStatus(queryError) === 403
    return (
      <div className="p-6">
        <Callout variant="error" title={forbidden ? 'Нет доступа к журналу приёмок' : 'Не удалось получить журнал приёмок'}
                 icon={AlertTriangle} role="alert">
          <p>{forbidden ? 'Запрос отклонён сервером. Проверьте роль и доступ к компании.' : mutationError(queryError, 'Проверьте подключение и повторите запрос.')}</p>
          <Button size="sm" variant="outline" className="mt-3"
                  onClick={() => void (stationQuery.isError ? stationQuery.refetch() : receiptsQuery.refetch())}>
            Повторить
          </Button>
        </Callout>
      </div>
    )
  }

  if (stationQuery.isSuccess && stationIds.length === 0) {
    return (
      <div className="p-6">
        <Callout variant="neutral" title="Нет доступных станций">
          В выбранной области нет станций, к которым у вас есть доступ. Журнал без явной области не запрашивался.
        </Callout>
      </div>
    )
  }

  if (open) {
    return <ReceiptCard receipt={open} onClose={() => setOpenId(null)}
                        onlyDiff={onlyDiff} setOnlyDiff={setOnlyDiff}
                        stationIds={stationIds} onReceiptChange={cacheReceipt} />
  }

  const receipts = data?.receipts ?? []
  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">Приёмка</h3>
          <p className="text-xs text-muted-foreground">
            Поступление товара от поставщика. Пока документ не принят, остатки не двигаются —
            это ордерная схема: «к поступлению» → «принят».
            {stationId
              ? ` Показана АЗС ${stationId}.`
              : ` Показаны разрешённые станции: ${stationIds.join(', ')}.`}
          </p>
        </div>
        <Button className="w-full sm:w-auto" onClick={() => setCreateOpen(true)}><Plus />Новая приёмка</Button>
      </div>

      {receipts.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/50 p-6 text-sm text-muted-foreground">
          Приёмок ещё нет. Заведите накладную здесь или примите товар на станции — документ
          будет один и тот же.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="px-3 py-2 text-left">Документ</th>
                <th className="px-3 py-2 text-left">Дата</th>
                <th className="px-3 py-2 text-left">АЗС</th>
                <th className="px-3 py-2 text-left">Поставщик</th>
                <th className="px-3 py-2 text-left">Статус</th>
                <th className="px-3 py-2 text-right">Позиций</th>
                <th className="px-3 py-2 text-right">Расхождений</th>
                <th className="px-3 py-2 text-right">Сумма, ₽</th>
                <th className="px-3 py-2 text-left">Ввод</th>
                {/* Кто принял: приёмка, проведённая из центра, коробок не открывала. */}
                <th className="px-3 py-2 text-left">Принял</th>
              </tr>
            </thead>
            <tbody>
              {receipts.map((r) => (
                <tr key={r.id} onClick={() => setOpenId(r.id)} tabIndex={0} role="button"
                    aria-label={`Открыть приёмку ${r.number}`}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        setOpenId(r.id)
                      }
                    }}
                    className="cursor-pointer border-b border-border outline-none last:border-0 hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                  <td className="px-3 py-2 font-medium">{r.number}</td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {shortDate(r.doc_date)}
                  </td>
                  <td className="px-3 py-2">{r.station_id ?? r.receiving_warehouse ?? 'центральный склад'}</td>
                  <td className="px-3 py-2">{r.supplier ?? <span className="text-muted-foreground">—</span>}</td>
                  <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.lines_count}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${r.diff_count ? 'text-amber-400/90' : ''}`}>
                    {r.diff_count || '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{money(r.total_amount)}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {r.origin === 'station' ? 'станция' : r.origin === 'edo' ? 'ЭДО' : 'центр'}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {r.author ?? <span className="text-muted-foreground/60">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <NewReceiptDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        defaultStation={stationId}
        stationIds={stationIds}
        onCreated={(receipt) => { cacheReceipt(receipt, true); setOpenId(receipt.id) }}
      />
    </div>
  )
}

/** Карточка документа: шапка, строки, перевод статуса. */
function ReceiptCard({ receipt, onClose, onlyDiff, setOnlyDiff, stationIds, onReceiptChange }: {
  receipt: StoreReceipt; onClose: () => void
  onlyDiff: boolean; setOnlyDiff: (v: boolean) => void
  stationIds: number[]
  onReceiptChange: (receipt: StoreReceipt) => void
}) {
  const actionLockRef = useRef(false)
  const counterpartiesQuery = useCounterparties()
  const contractsQuery = useContracts()
  const organizationsQuery = useOrganizations()
  const [supplierId, setSupplierId] = useState<string | null>(receipt.supplier_id ?? null)
  const [supplier, setSupplier] = useState(receipt.supplier ?? '')
  const [contractId, setContractId] = useState<string | null>(receipt.contract_id ?? null)
  const [contract, setContract] = useState(receipt.contract ?? '')
  const [incoming, setIncoming] = useState(receipt.incoming_number ?? '')
  const [incomingDate, setIncomingDate] = useState(receipt.incoming_date?.slice(0, 10) ?? '')
  const [docDate, setDocDate] = useState(receipt.doc_date.slice(0, 10))
  const [comment, setComment] = useState(receipt.comment ?? '')
  const [lines, setLines] = useState<StoreReceiptLine[]>(receipt.lines ?? [])
  const [signatureRef, setSignatureRef] = useState(receipt.signature_ref ?? '')
  const [signerName, setSignerName] = useState(receipt.signer_name ?? '')
  const [mchdGuid, setMchdGuid] = useState(receipt.mchd_guid ?? '')
  const [mchdRegistry, setMchdRegistry] = useState(receipt.mchd_registry ?? '')
  const [mchdUntil, setMchdUntil] = useState(receipt.mchd_valid_until ?? '')
  const [scanPending, setScanPending] = useState(false)
  const [permissionDenied, setPermissionDenied] = useState(false)
  const [notice, setNotice] = useState<{
    state: 'pending' | 'success' | 'error'
    title: string
    detail?: string
    action?: 'save' | 'accept' | 'send' | 'sign' | 'refresh'
    conflict?: boolean
  } | null>(null)
  const readOnly = receipt.status === 'accepted' || receipt.status === 'reversed' || permissionDenied
  const canFinalize = !!supplierId && !!contractId
  const finalizeReason = !supplierId
    ? 'Сначала подтвердите поставщика в центре'
    : !contractId
      ? 'Сначала выберите канонический договор поставщика'
      : null
  const counterparties = (counterpartiesQuery.data ?? [])
    .filter((counterparty) => !counterparty.kind || counterparty.kind === 'external')
  const selectedSupplier = counterparties.find((counterparty) => counterparty.id === supplierId)
  const draftStationId = receipt.station_id ?? (stationIds.length === 1 ? stationIds[0] : null)

  const hydrateForm = (updated: StoreReceipt) => {
    setSupplierId(updated.supplier_id ?? null)
    setSupplier(updated.supplier ?? '')
    setContractId(updated.contract_id ?? null)
    setContract(updated.contract ?? '')
    setIncoming(updated.incoming_number ?? '')
    setIncomingDate(updated.incoming_date?.slice(0, 10) ?? '')
    setDocDate(updated.doc_date.slice(0, 10))
    setComment(updated.comment ?? '')
    setLines(updated.lines)
    setSignatureRef(updated.signature_ref ?? '')
    setSignerName(updated.signer_name ?? '')
    setMchdGuid(updated.mchd_guid ?? '')
    setMchdRegistry(updated.mchd_registry ?? '')
    setMchdUntil(updated.mchd_valid_until ?? '')
  }

  const body = (): StoreReceiptInput => ({
    station_id: receipt.station_id, number: receipt.number,
    doc_date: docDate || receipt.doc_date,
    supplier_id: supplierId, supplier: supplier || null,
    contract_id: contractId, contract: contract || null,
    incoming_number: incoming || null, incoming_date: incomingDate || null,
    comment: comment || null, lines,
    delivery_scheme: receipt.delivery_scheme,
    receiving_warehouse: receipt.receiving_warehouse,
    signing_mode: receipt.signing_mode,
    signer_name: signerName || null, mchd_guid: mchdGuid || null,
    mchd_registry: mchdRegistry || null, mchd_valid_until: mchdUntil || null,
    signature_status: receipt.signature_status, signature_ref: receipt.signature_ref,
    version: receipt.version,
  })

  const releaseAction = () => { actionLockRef.current = false }
  const failAction = (
    error: unknown,
    fallback: string,
    action: 'save' | 'accept' | 'send' | 'sign' | 'refresh',
  ) => {
    if (apiStatus(error) === 403) setPermissionDenied(true)
    setNotice({
      state: 'error',
      title: apiStatus(error) === 409 ? 'Конфликт документа' : 'Операция не выполнена',
      detail: mutationError(error, fallback),
      action: apiStatus(error) === 403 ? undefined : action,
      conflict: apiStatus(error) === 409,
    })
  }

  const save = useMutation({
    mutationFn: (payload: StoreReceiptInput) => updateStoreReceipt(receipt.id, payload),
    onSuccess: (updated) => {
      onReceiptChange(updated)
      setLines(updated.lines)
      setNotice({ state: 'success', title: 'Изменения сохранены' })
    },
    onError: (error) => failAction(error, 'Повторите сохранение.', 'save'),
    onSettled: releaseAction,
  })
  const accept = useMutation({
    mutationFn: async (payload: StoreReceiptInput) => {
      const updated = await updateStoreReceipt(receipt.id, payload)
      return setStoreReceiptStatus(receipt.id, 'accepted', updated.version)
    },
    onSuccess: (updated) => {
      onReceiptChange(updated)
      setNotice({ state: 'success', title: 'Приёмка проведена' })
      onClose()
    },
    onError: (error) => failAction(error, 'Проверьте документ и повторите приёмку.', 'accept'),
    onSettled: releaseAction,
  })
  const send = useMutation({
    mutationFn: async (payload: StoreReceiptInput) => {
      const updated = await updateStoreReceipt(receipt.id, payload)
      await sendStoreReceiptToStation(receipt.id, updated.version)
      return getStoreReceipt(receipt.id)
    },
    onSuccess: (updated) => {
      onReceiptChange(updated)
      hydrateForm(updated)
      setNotice({ state: 'success', title: 'Документ передан на АЗС' })
    },
    onError: (error) => failAction(error, 'Повторите передачу на станцию.', 'send'),
    onSettled: releaseAction,
  })
  const sign = useMutation({
    mutationFn: (payload: Parameters<typeof recordStoreReceiptSignature>[1]) =>
      recordStoreReceiptSignature(receipt.id, payload),
    onSuccess: (updated) => {
      onReceiptChange(updated)
      setNotice({ state: 'success', title: 'Подпись ЭДО зафиксирована' })
    },
    onError: (error) => failAction(error, 'Повторите фиксацию подписи.', 'sign'),
    onSettled: releaseAction,
  })
  const refresh = useMutation({
    mutationFn: () => getStoreReceipt(receipt.id),
    onSuccess: (updated) => {
      onReceiptChange(updated)
      hydrateForm(updated)
      setNotice({ state: 'success', title: 'Документ обновлён' })
    },
    onError: (error) => failAction(error, 'Не удалось обновить документ.', 'refresh'),
    onSettled: releaseAction,
  })

  const beginAction = (
    action: 'save' | 'accept' | 'send' | 'sign' | 'refresh',
    title: string,
  ) => {
    if (actionLockRef.current) return
    actionLockRef.current = true
    setNotice({ state: 'pending', title })
    if (action === 'save') save.mutate(body())
    if (action === 'accept') accept.mutate(body())
    if (action === 'send') send.mutate(body())
    if (action === 'sign') sign.mutate({
      signature_status: 'signed', signature_ref: signatureRef || null,
      signer_name: signerName || null, mchd_guid: mchdGuid || null,
      mchd_registry: mchdRegistry || null, mchd_valid_until: mchdUntil || null,
      version: receipt.version,
    })
    if (action === 'refresh') refresh.mutate()
  }
  const actionBusy = notice?.state === 'pending'
  const isBusy = actionBusy || scanPending

  const setLine = (i: number, patch: Partial<StoreReceiptLine>) =>
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)))

  const total = lines.reduce((s, l) => s + (l.qty_fact || 0) * (l.price || 0), 0)
  const diffCount = lines.filter((l) => Math.abs((l.qty_fact || 0) - (l.qty_expected || 0)) > 1e-6).length
  const linesDirty = useMemo(
    () => JSON.stringify(lines) !== JSON.stringify(receipt.lines),
    [lines, receipt.lines],
  )
  const shown = onlyDiff
    ? lines.filter((l) => Math.abs((l.qty_fact || 0) - (l.qty_expected || 0)) > 1e-6)
    : lines

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <PackagePlus className="h-5 w-5 text-muted-foreground" />
          <div>
            <h3 className="text-base font-semibold">{receipt.number}</h3>
            <p className="text-xs text-muted-foreground">
              {receipt.delivery_scheme === 'central_warehouse'
                ? receipt.receiving_warehouse
                : `АЗС ${receipt.station_id}`} · {shortDate(receipt.doc_date)} ·{' '}
              <StatusBadge status={receipt.status} />
            </p>
          </div>
        </div>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
          <button onClick={onClose} disabled={isBusy}
                  className="rounded-lg border border-border px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
            К журналу
          </button>
          {!readOnly && (
            <>
              {receipt.delivery_scheme === 'supplier_to_station' && (
                <Button variant="outline" onClick={() => beginAction('send', 'Передаём документ на АЗС…')}
                        disabled={isBusy || !canFinalize}
                        title={finalizeReason ?? 'Передать документ на АЗС'}>
                  {send.isPending ? <Loader2 className="animate-spin" /> : <Send />}На АЗС
                </Button>
              )}
              <button onClick={() => beginAction('save', 'Сохраняем изменения…')} disabled={isBusy}
                      className="rounded-lg border border-border px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
                {save.isPending ? 'Сохраняем…' : 'Сохранить'}
              </button>
              {receipt.delivery_scheme === 'central_warehouse' && (
                <button onClick={() => beginAction('accept', 'Проводим приёмку…')} disabled={isBusy || !canFinalize}
                        title={finalizeReason ?? 'Принять на центральный склад'}
                        className="inline-flex items-center gap-2 rounded-lg bg-emerald-600/90 px-3 py-2 text-sm text-white outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
                  {accept.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  {accept.isPending ? 'Проводим…' : 'Принять на центральный склад'}
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {(receipt.status === 'accepted' || receipt.status === 'reversed') && (
        <Callout variant="neutral"
                 title={receipt.status === 'accepted' ? 'Документ принят — режим только чтение' : 'Документ сторнирован — режим только чтение'}>
          {receipt.status === 'accepted'
            ? 'Остатки уже изменены. Для корректировки оформите следующий складской документ.'
            : 'Сторно уже зафиксировано. Изменять исходный документ нельзя.'}
        </Callout>
      )}
      {permissionDenied && (
        <Callout variant="warning" title="Режим только чтение" icon={AlertTriangle} role="alert">
          Сервер отклонил изменение с кодом 403. Просмотр сохранён, для редактирования запросите нужную роль.
        </Callout>
      )}
      {!readOnly && supplier && !supplierId && (
        <Callout variant="warning" title="Поставщик ещё не подтверждён" icon={AlertTriangle}>
          Текстовый снимок или черновик поставщика можно сохранить, но передать документ на АЗС
          или принять товар нельзя, пока центр не свяжет его с канонической карточкой.
        </Callout>
      )}
      {!readOnly && supplierId && !contractId && (
        <Callout variant="warning" title="Договор ещё не выбран" icon={AlertTriangle}>
          Документ можно сохранить как черновик, но передать его на АЗС или принять товар нельзя
          без канонического договора вида «С поставщиком».
        </Callout>
      )}
      {notice && (
        <div aria-live={notice.state === 'error' ? 'assertive' : 'polite'} aria-atomic="true">
          <Callout
            variant={notice.state === 'error' ? 'error' : notice.state === 'success' ? 'success' : 'default'}
            title={notice.title}
            icon={notice.state === 'error' ? AlertTriangle : notice.state === 'pending' ? Loader2 : CircleCheck}
            role={notice.state === 'error' ? 'alert' : 'status'}
          >
            {notice.detail ? <p>{notice.detail}</p> : null}
            {notice.state === 'error' && notice.action ? (
              <Button size="sm" variant="outline" className="mt-3"
                      onClick={() => beginAction(
                        notice.conflict ? 'refresh' : notice.action!,
                        notice.conflict || notice.action === 'refresh' ? 'Обновляем документ…' : 'Повторяем операцию…',
                      )}>
                {notice.conflict ? 'Обновить документ' : 'Повторить'}
              </Button>
            ) : null}
          </Callout>
        </div>
      )}

      <div className="grid gap-4 rounded-xl border border-border bg-card p-4 lg:grid-cols-2">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Warehouse className="h-4 w-4" />
            {receipt.delivery_scheme === 'central_warehouse'
              ? 'Поставщик → центральный склад'
              : `Поставщик → АЗС ${receipt.station_id}`}
          </div>
          <p className="text-xs text-muted-foreground">
            {receipt.delivery_scheme === 'central_warehouse'
              ? 'После приёмки партия распределяется на АЗС внутренними перемещениями.'
              : 'Базовая схема: УПД сформирован в разрезе конкретной станции и её склада.'}
          </p>
        </div>
        <div className="space-y-3">
          <div className="text-sm font-medium">
            {receipt.signing_mode === 'station_mchd'
              ? 'Администратор АЗС — личная УКЭП по МЧД'
              : 'Офис — подпись генерального директора'}
          </div>
          {receipt.signature_status === 'signed' ? (
            <p className="text-xs text-emerald-400">
              Подписан в ЭДО · {receipt.signature_ref}
            </p>
          ) : (
            <>
              {receipt.signing_mode === 'station_mchd' && (
                <div className="grid gap-2 sm:grid-cols-2">
                  <Input value={signerName} onChange={(e) => setSignerName(e.target.value)} disabled={readOnly || isBusy} placeholder="ФИО представителя" />
                  <Input value={mchdGuid} onChange={(e) => setMchdGuid(e.target.value)} disabled={readOnly || isBusy} placeholder="GUID МЧД" />
                  <Input value={mchdRegistry} onChange={(e) => setMchdRegistry(e.target.value)} disabled={readOnly || isBusy} placeholder="Реестр МЧД" />
                  <Input type="date" value={mchdUntil} onChange={(e) => setMchdUntil(e.target.value)} disabled={readOnly || isBusy} />
                </div>
              )}
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input value={signatureRef} onChange={(e) => setSignatureRef(e.target.value)}
                       disabled={readOnly || isBusy} placeholder="Идентификатор подписи оператора ЭДО" />
                <Button variant="outline" onClick={() => beginAction('sign', 'Фиксируем подпись ЭДО…')}
                        disabled={readOnly || isBusy || !signatureRef.trim()}>
                  {sign.isPending ? <Loader2 className="animate-spin" /> : null}
                  {sign.isPending ? 'Фиксируем…' : 'Зафиксировать подпись ЭДО'}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Здесь фиксируются реквизиты уже выполненной подписи; криптографическая операция проходит у оператора ЭДО.
              </p>
            </>
          )}
        </div>
      </div>

      {!readOnly && receipt.delivery_scheme === 'central_warehouse' && (
        <ReceiptScanner
          receipt={receipt}
          disabledReason={linesDirty
            ? 'Сканирование использует серверную версию документа. Сохраните изменённые строки перед сканом.'
            : actionBusy ? 'Дождитесь завершения текущей операции с документом.' : null}
          onPendingChange={setScanPending}
          onScanned={(result) => {
            setLines(result.lines)
            onReceiptChange(result)
          }}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-xs text-muted-foreground">Дата документа
          <Input type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)}
                 disabled={readOnly || isBusy} className="mt-1" />
        </label>
        <SupplierPicker
          supplierId={supplierId}
          snapshot={supplier}
          counterparties={counterparties}
          disabled={readOnly || isBusy}
          isLoading={counterpartiesQuery.isLoading}
          error={counterpartiesQuery.error}
          draftStationId={draftStationId}
          receiptNumber={receipt.number}
          onChange={(nextSupplierId, nextSnapshot) => {
            if (nextSupplierId !== supplierId || nextSnapshot !== supplier) {
              setContractId(null)
              setContract('')
            }
            setSupplierId(nextSupplierId)
            setSupplier(nextSnapshot)
          }}
        />
        <ContractPicker
          contractId={contractId}
          snapshot={contract}
          supplier={selectedSupplier}
          contracts={contractsQuery.data ?? []}
          organizations={organizationsQuery.data ?? []}
          disabled={readOnly || isBusy}
          isLoading={contractsQuery.isLoading || organizationsQuery.isLoading}
          error={contractsQuery.error}
          organizationError={organizationsQuery.error}
          onChange={(nextContractId, nextSnapshot) => {
            setContractId(nextContractId)
            setContract(nextSnapshot)
          }}
        />
        <label className="text-xs text-muted-foreground">Входящий номер
          <input value={incoming} onChange={(e) => setIncoming(e.target.value)} disabled={readOnly || isBusy}
                 className="mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-base text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 sm:text-sm" />
        </label>
        <label className="text-xs text-muted-foreground">Дата входящего документа
          <Input type="date" value={incomingDate} onChange={(e) => setIncomingDate(e.target.value)}
                 disabled={readOnly || isBusy} className="mt-1" />
        </label>
        <div className="rounded-lg border border-border bg-card px-3 py-2">
          <div className="text-xs text-muted-foreground">Сумма по факту</div>
          <div className="text-lg font-semibold tabular-nums">{money(total)} ₽</div>
        </div>
        <div className="rounded-lg border border-border bg-card px-3 py-2">
          <div className="text-xs text-muted-foreground">Расхождений</div>
          <div className={`text-lg font-semibold tabular-nums ${diffCount ? 'text-amber-400/90' : ''}`}>
            {diffCount}
          </div>
        </div>
      </div>

      <label className="block text-xs text-muted-foreground">Комментарий
        <Textarea value={comment} onChange={(event) => setComment(event.target.value)}
                  disabled={readOnly || isBusy} className="mt-1 resize-y" rows={2} />
      </label>

      <div className="flex items-center gap-3">
        <button onClick={() => setOnlyDiff(!onlyDiff)} aria-pressed={onlyDiff}
                className={`rounded-lg border px-3 py-1.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring ${onlyDiff ? 'border-amber-400/50 text-amber-300/90' : 'border-border text-muted-foreground'}`}>
          Только строки с расхождениями
        </button>
        {!readOnly && (
          <button onClick={() => setLines((current) => [...current, emptyLine()])} disabled={isBusy}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
            <Plus className="h-3.5 w-3.5" />Позиция
          </button>
        )}
        <span className="text-xs text-muted-foreground">
          Заявлено — из накладной, факт — сколько реально посчитали. Платим за факт.
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground">
              <th className="px-3 py-2 text-left">Наименование</th>
              <th className="px-3 py-2 text-left">Штрихкод</th>
              <th className="px-3 py-2 text-right">Заявлено</th>
              <th className="px-3 py-2 text-right">Факт</th>
              <th className="px-3 py-2 text-right">Расхождение</th>
              <th className="px-3 py-2 text-right">Цена</th>
              <th className="px-3 py-2 text-right">Сумма</th>
              {!readOnly && <th className="px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {shown.map((l) => {
              const i = lines.indexOf(l)
              const diff = (l.qty_fact || 0) - (l.qty_expected || 0)
              return (
                <tr key={i} className="border-b border-border last:border-0">
                  <td className="px-3 py-1.5">
                    <input value={l.name} onChange={(e) => setLine(i, { name: e.target.value })}
                           disabled={readOnly || isBusy} placeholder="наименование"
                           className="w-full bg-transparent text-base outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70 sm:text-sm" />
                  </td>
                  <td className="px-3 py-1.5">
                    <input value={l.barcode ?? ''} onChange={(e) => setLine(i, { barcode: e.target.value })}
                           disabled={readOnly || isBusy} placeholder="сканируйте"
                           className="w-36 bg-transparent text-base text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70 sm:text-sm" />
                    {l.requires_mark ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Badge variant="outline">УПД: {l.upd_codes?.length ?? 0}</Badge>
                        <Badge variant={(l.mark_codes?.length ?? 0) === l.qty_fact ? 'secondary' : 'destructive'}>
                          сканов: {l.mark_codes?.length ?? 0}
                        </Badge>
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input type="number" value={l.qty_expected}
                           onChange={(e) => setLine(i, { qty_expected: Number(e.target.value) })}
                           disabled={readOnly || isBusy}
                           className="w-20 bg-transparent text-right text-base tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70 sm:text-sm" />
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input type="number" value={l.qty_fact}
                           onChange={(e) => setLine(i, { qty_fact: Number(e.target.value) })}
                           disabled={readOnly || isBusy}
                           className="w-20 bg-transparent text-right text-base tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70 sm:text-sm" />
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${diff ? 'text-amber-400/90' : 'text-muted-foreground'}`}>
                    {diff ? (diff > 0 ? `+${diff}` : diff) : '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input type="number" value={l.price}
                           onChange={(e) => setLine(i, { price: Number(e.target.value) })}
                           disabled={readOnly || isBusy}
                           className="w-24 bg-transparent text-right text-base tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70 sm:text-sm" />
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {money((l.qty_fact || 0) * (l.price || 0))}
                  </td>
                  {!readOnly && (
                    <td className="px-3 py-1.5 text-right">
                      <button onClick={() => setLines((current) => current.filter((_, idx) => idx !== i))}
                              disabled={isBusy} aria-label={`Удалить позицию ${l.name || i + 1}`}
                              title="Удалить позицию"
                              className="rounded text-muted-foreground outline-none hover:text-red-400 focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  )}
                </tr>
              )
            })}
            {shown.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-sm text-muted-foreground">
                {lines.length ? 'Расхождений нет' : 'Добавьте позиции или примите товар на станции'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {receipt.status === 'accepted' && receipt.delivery_scheme === 'central_warehouse' && (
        <DistributionPanel receipt={receipt} stationIds={stationIds} onReceiptChange={onReceiptChange} />
      )}
    </div>
  )
}

function ReceiptScanner({ receipt, disabledReason, onPendingChange, onScanned }: {
  receipt: StoreReceipt
  disabledReason: string | null
  onPendingChange: (pending: boolean) => void
  onScanned: (receipt: StoreReceipt) => void
}) {
  const disabled = disabledReason !== null
  const inputRef = useRef<HTMLInputElement>(null)
  const scanLockRef = useRef(false)
  const [code, setCode] = useState('')
  const [feedback, setFeedback] = useState<{
    kind: 'pending' | 'success' | 'error'; title: string; detail: string; type?: string
  } | null>(null)
  const [scans, setScans] = useState(0)

  const scan = useMutation({
    mutationFn: ({ barcode }: { barcode: string }) =>
      scanStoreReceipt(receipt.id, barcode, 1),
    onMutate: () => onPendingChange(true),
    onSuccess: (result) => {
      setScans((count) => count + 1)
      setFeedback({
        kind: 'success', title: result.scan.name || 'Товар найден',
        detail: `Добавлено: ${result.scan.qty_added.toLocaleString('ru-RU', { maximumFractionDigits: 3 })} · штрихкод ${result.scan.barcode}`,
        type: result.scan.type,
      })
      onScanned(result)
    },
    onError: (error, variables) => {
      setCode(variables.barcode)
      setFeedback({
        kind: 'error',
        title: apiStatus(error) === 409 ? 'Скан конфликтует с документом' : 'Скан не принят',
        detail: mutationError(error, 'Проверьте код и повторите сканирование.'),
      })
    },
    onSettled: () => {
      scanLockRef.current = false
      onPendingChange(false)
      window.setTimeout(() => inputRef.current?.focus(), 0)
    },
  })

  const submit = () => {
    if (scanLockRef.current || disabled) return
    const parsed = parseReceiptScan(code)
    if (!parsed) {
      setFeedback({ kind: 'error', title: 'Сканер не передал код', detail: 'Поставьте курсор в поле и повторите сканирование.' })
      inputRef.current?.focus()
      return
    }
    if (parsed.checksumValid === false) {
      setFeedback({
        kind: 'error', title: 'Контрольная цифра не сходится',
        detail: `${SCAN_TYPE_LABEL[parsed.type]} прочитан с ошибкой. Повторите сканирование.`,
      })
      setCode('')
      inputRef.current?.focus()
      return
    }
    scanLockRef.current = true
    setFeedback({
      kind: 'pending', title: 'Проверяем скан…',
      detail: `${SCAN_TYPE_LABEL[parsed.type]} · ${parsed.productBarcode}`,
      type: parsed.type,
    })
    setCode('')
    scan.mutate({ barcode: parsed.raw })
  }

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4"
             aria-labelledby="receipt-scanner-title" aria-busy={scan.isPending}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 id="receipt-scanner-title" className="flex items-center gap-2 text-sm font-semibold">
            <ScanBarcode className="size-4" />Поточное сканирование
          </h4>
          <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
            USB- и радиосканер работает как клавиатура: наведите на код, сканер введёт его и нажмёт Enter.
            Поддерживаются EAN-8/13, UPC-A, GTIN-14, Code 128, GS1-128, DataMatrix и табачная маркировка.
          </p>
        </div>
        <Badge variant="secondary">Сканов за сеанс: {scans}</Badge>
      </div>
      <form className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}>
        <label className="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
          Код со сканера
          <Input ref={inputRef} autoFocus autoComplete="off" value={code} maxLength={512}
                 disabled={scan.isPending || disabled} onChange={(event) => setCode(event.target.value)}
                 aria-describedby="receipt-scanner-hint"
                 placeholder="поле остаётся в фокусе после каждого скана" />
        </label>
        <Button type="submit" className="w-full self-end sm:w-auto" disabled={scan.isPending || disabled || !code}>
          {scan.isPending ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <ScanBarcode data-icon="inline-start" />}
          {scan.isPending ? 'Проверяем…' : 'Принять скан'}
        </Button>
      </form>
      <p id="receipt-scanner-hint" className="text-xs text-muted-foreground">
        Один скан добавляет одну единицу. Для маркированного товара повторный код и код не из УПД блокируются.
        Весовая этикетка принимается автоматически только при точном штрихкоде в НСИ — масса не угадывается по локальному префиксу.
      </p>
      {disabledReason ? (
        <Callout variant="warning" title={disabledReason.startsWith('Сканирование') ? 'Сначала сохраните изменения' : 'Сканирование временно недоступно'}>
          {disabledReason}
        </Callout>
      ) : null}
      {feedback && (
        <div aria-live={feedback.kind === 'error' ? 'assertive' : 'polite'} aria-atomic="true">
          <Callout variant={feedback.kind === 'success' ? 'success' : feedback.kind === 'error' ? 'error' : 'default'}
                   title={feedback.title}
                   role={feedback.kind === 'error' ? 'alert' : 'status'}
                   icon={feedback.kind === 'success' ? CircleCheck : feedback.kind === 'error' ? AlertTriangle : Loader2}>
            <span>{feedback.detail}</span>
            {feedback.type ? <Badge variant="outline" className="ml-2">{feedback.type}</Badge> : null}
            {feedback.kind === 'error' && code ? (
              <Button type="button" size="sm" variant="outline" className="mt-3"
                      onClick={submit} disabled={scan.isPending || disabled}>
                Повторить скан
              </Button>
            ) : null}
          </Callout>
        </div>
      )}
    </section>
  )
}

function NewReceiptDialog({ open, onOpenChange, defaultStation, stationIds, onCreated }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultStation?: number
  stationIds: number[]
  onCreated: (receipt: StoreReceipt) => void
}) {
  const createLockRef = useRef(false)
  const firstStation = defaultStation ?? stationIds[0]
  const [delivery, setDelivery] = useState<'supplier_to_station' | 'central_warehouse'>('supplier_to_station')
  const [station, setStation] = useState(firstStation ? String(firstStation) : '')
  const [warehouse, setWarehouse] = useState('Центральный склад')
  const [signing, setSigning] = useState<'office_director' | 'station_mchd'>('office_director')
  const [signerName, setSignerName] = useState('')
  const [mchdGuid, setMchdGuid] = useState('')
  const [mchdRegistry, setMchdRegistry] = useState('ФНС')
  const [mchdUntil, setMchdUntil] = useState('')
  const [upd, setUpd] = useState<File | null>(null)

  const options: StoreReceiptInput = {
    station_id: delivery === 'supplier_to_station' ? Number(station) : null,
    delivery_scheme: delivery,
    receiving_warehouse: delivery === 'central_warehouse' ? warehouse : null,
    signing_mode: delivery === 'central_warehouse' ? 'office_director' : signing,
    signer_name: signing === 'station_mchd' ? signerName || null : null,
    mchd_guid: signing === 'station_mchd' ? mchdGuid || null : null,
    mchd_registry: signing === 'station_mchd' ? mchdRegistry || null : null,
    mchd_valid_until: signing === 'station_mchd' ? mchdUntil || null : null,
    signature_status: 'pending', signature_ref: null, lines: [],
  }
  const create = useMutation({
    mutationFn: () => upd
      ? createStoreReceiptFromUPD(upd, options)
      : createStoreReceipt(options),
    onSuccess: (receipt) => {
      onCreated(receipt)
      onOpenChange(false)
    },
    onSettled: () => { createLockRef.current = false },
  })
  const submit = () => {
    if (createLockRef.current || create.isPending) return
    createLockRef.current = true
    create.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => {
      if (!create.isPending) onOpenChange(nextOpen)
    }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Новая приёмка</DialogTitle>
          <DialogDescription>
            Сначала выберите маршрут товара, затем — кто подпишет УПД. Прямая доставка на АЗС используется по умолчанию.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-5 py-2">
          <label className="grid gap-2 text-sm">
            Доставка
            <Select value={delivery} onValueChange={(value) => {
              const next = value as 'supplier_to_station' | 'central_warehouse'
              setDelivery(next)
              if (next === 'central_warehouse') setSigning('office_director')
            }}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="supplier_to_station">Поставщик → конкретная АЗС (по умолчанию)</SelectItem>
                  <SelectItem value="central_warehouse">Поставщик → центральный склад</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
          {delivery === 'supplier_to_station' ? (
            <label className="grid gap-2 text-sm">
              Станция-получатель
              <Select value={station} onValueChange={setStation}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {stationIds.map((id) => (
                      <SelectItem key={id} value={String(id)}>АЗС {id}</SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </label>
          ) : (
            <label className="grid gap-2 text-sm">Склад приёмки
              <Input value={warehouse} onChange={(e) => setWarehouse(e.target.value)} />
              <span className="text-xs text-muted-foreground">После приёмки товар распределяется внутренними перемещениями.</span>
            </label>
          )}
          <label className="grid gap-2 text-sm">
            Подписание УПД
            <Select value={delivery === 'central_warehouse' ? 'office_director' : signing}
                    disabled={delivery === 'central_warehouse'}
                    onValueChange={(value) => setSigning(value as 'office_director' | 'station_mchd')}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="office_director">Офис — генеральный директор</SelectItem>
                  <SelectItem value="station_mchd">Администратор АЗС — УКЭП по МЧД</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
          {delivery === 'supplier_to_station' && signing === 'station_mchd' && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Input value={signerName} onChange={(e) => setSignerName(e.target.value)} placeholder="ФИО представителя" />
              <Input value={mchdGuid} onChange={(e) => setMchdGuid(e.target.value)} placeholder="GUID МЧД" />
              <Input value={mchdRegistry} onChange={(e) => setMchdRegistry(e.target.value)} placeholder="Реестр МЧД" />
              <Input type="date" value={mchdUntil} onChange={(e) => setMchdUntil(e.target.value)} />
            </div>
          )}
          <label className="grid gap-2 text-sm">УПД из ЭДО <span className="text-xs text-muted-foreground">необязательно для черновика</span>
            <Input type="file" accept=".xml,text/xml,application/xml" onChange={(e) => setUpd(e.target.files?.[0] ?? null)} />
          </label>
          {create.isError && (
            <Callout variant={apiStatus(create.error) === 403 ? 'warning' : 'error'}
                     title={apiStatus(create.error) === 403 ? 'Недостаточно прав' : 'Приёмка не создана'}
                     icon={AlertTriangle} role="alert">
              {mutationError(create.error, 'Проверьте поля и повторите создание.')}
            </Callout>
          )}
          {create.isPending && <p className="text-sm text-muted-foreground" role="status" aria-live="polite">Создаём приёмку…</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={create.isPending}>Отмена</Button>
          <Button onClick={submit}
                  disabled={create.isPending || (delivery === 'supplier_to_station' && !station)}>
            {create.isPending ? <Loader2 className="animate-spin" /> : null}
            {create.isPending ? 'Создаём…' : create.isError ? 'Повторить создание' : 'Создать приёмку'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DistributionPanel({ receipt, stationIds, onReceiptChange }: {
  receipt: StoreReceipt
  stationIds: number[]
  onReceiptChange: (receipt: StoreReceipt) => void
}) {
  const distributeLockRef = useRef(false)
  const [station, setStation] = useState(stationIds[0] ? String(stationIds[0]) : '')
  const [qty, setQty] = useState<Record<number, number>>({})
  const used = new Map<number, number>()
  receipt.distribution.forEach((allocation) => allocation.lines.forEach((line) => {
    used.set(line.line_index, (used.get(line.line_index) ?? 0) + line.qty)
  }))
  const distribute = useMutation({
    mutationFn: async () => {
      await distributeStoreReceipt(
        receipt.id, Number(station),
        Object.entries(qty).filter(([, value]) => value > 0)
          .map(([lineIndex, value]) => ({ line_index: Number(lineIndex), qty: value })),
        receipt.version,
      )
      return getStoreReceipt(receipt.id)
    },
    onSuccess: (updated) => {
      setQty({})
      onReceiptChange(updated)
    },
    onSettled: () => { distributeLockRef.current = false },
  })
  const hasQuantity = Object.values(qty).some((value) => value > 0)
  const submit = () => {
    if (distributeLockRef.current || distribute.isPending || !station || !hasQuantity) return
    distributeLockRef.current = true
    distribute.mutate()
  }

  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div>
        <h4 className="text-sm font-semibold">Распределение по станциям</h4>
        <p className="text-xs text-muted-foreground">Создаётся внутреннее перемещение с центрального склада, не второй приход поставщика.</p>
      </div>
      <Select value={station} onValueChange={setStation}>
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent><SelectGroup>{stationIds.map((id) => (
          <SelectItem key={id} value={String(id)}>АЗС {id}</SelectItem>
        ))}</SelectGroup></SelectContent>
      </Select>
      <div className="grid gap-2">
        {receipt.lines.map((line, index) => {
          const available = Math.max(0, line.qty_fact - (used.get(index) ?? 0))
          return (
            <label key={index} className="grid grid-cols-[1fr_110px] items-center gap-3 text-sm">
              <span>{line.name} <span className="text-xs text-muted-foreground">доступно {available}</span></span>
              <Input type="number" min={0} max={available} step="any" value={qty[index] ?? ''}
                     disabled={available <= 0 || distribute.isPending}
                     onChange={(e) => setQty((current) => ({ ...current, [index]: Number(e.target.value) }))} />
            </label>
          )
        })}
      </div>
      {distribute.isError && (
        <Callout variant={apiStatus(distribute.error) === 403 ? 'warning' : 'error'}
                 title={apiStatus(distribute.error) === 409 ? 'Конфликт распределения' : 'Распределение не выполнено'}
                 icon={AlertTriangle} role="alert">
          {mutationError(distribute.error, 'Проверьте количество и повторите передачу.')}
        </Callout>
      )}
      {distribute.isSuccess && (
        <p className="text-sm text-emerald-400" role="status" aria-live="polite">Перемещение на АЗС создано.</p>
      )}
      <Button onClick={submit}
              disabled={distribute.isPending || !station || !hasQuantity || apiStatus(distribute.error) === 403}>
        {distribute.isPending ? <Loader2 className="animate-spin" /> : <Send />}
        {distribute.isPending ? 'Передаём…' : distribute.isError ? 'Повторить передачу' : 'Передать на АЗС'}
      </Button>
    </div>
  )
}
