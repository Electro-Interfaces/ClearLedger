/**
 * Страница «1С → Справочники». Реализует pull-чтение НСИ из БП ГИГ
 * через backend TradeLedger. Четыре таба: Контрагенты, Номенклатура,
 * Склады, Организации. Кнопка «Обновить из 1С» запускает
 * sync_catalogs на первом активном коннекте компании.
 */

import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from '@/components/ui/tabs'
import { usePersistentState } from '@/hooks/usePersistentState'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Users, Package, Warehouse, Building2, Search, RefreshCw, Loader2,
  ChevronLeft, ChevronRight,
} from 'lucide-react'
import { toast } from 'sonner'
import { useCompany } from '@/contexts/CompanyContext'
import { useOneCConnections, useSyncCatalogs } from '@/hooks/useOneCSync'
import {
  searchCounterpartiesPaged,
  searchNomenclaturePaged,
  searchWarehousesPaged,
  searchOrganizationsPaged,
} from '@/services/referenceService'
import type { Counterparty, Organization, Nomenclature, Warehouse as Wh } from '@/types'

const PAGE_SIZE = 50

type TabKey = 'counterparties' | 'nomenclature' | 'warehouses' | 'organizations'

const TABS: { key: TabKey; label: string; icon: typeof Users }[] = [
  { key: 'counterparties', label: 'Контрагенты', icon: Users },
  { key: 'nomenclature',   label: 'Номенклатура', icon: Package },
  { key: 'warehouses',     label: 'Склады',       icon: Warehouse },
  { key: 'organizations',  label: 'Организации',  icon: Building2 },
]

export function ReferencesPage() {
  const { companyId } = useCompany()
  const { data: connections } = useOneCConnections()
  const syncMutation = useSyncCatalogs()
  const connection = connections?.[0]

  const [tab, setTab] = usePersistentState<TabKey>('cl-1c-references-tab', 'counterparties')

  async function handleSync() {
    if (!connection) {
      toast.error('Сначала создайте подключение к 1С на вкладке «Подключение»')
      return
    }
    const id = toast.loading('Тяну справочники из 1С — это занимает ~30 секунд')
    try {
      const r = await syncMutation.mutateAsync(connection.id)
      toast.dismiss(id)
      toast.success(
        `Готово. Создано ${r.stats.created}, обновлено ${r.stats.updated}, ошибок ${r.stats.errors}`,
      )
    } catch (err) {
      toast.dismiss(id)
      toast.error(err instanceof Error ? err.message : 'Ошибка sync_catalogs')
    }
  }

  return (
    <div className="space-y-4 max-w-6xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Справочники из 1С</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Реплицированные сущности БП ГИГ. Поиск, пагинация и обновление через pull-чтение.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={handleSync}
          disabled={!connection || syncMutation.isPending}
          className="gap-1.5 shrink-0"
        >
          {syncMutation.isPending
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <RefreshCw className="h-3.5 w-3.5" />}
          Обновить из 1С
        </Button>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
        <TabsList className="grid grid-cols-4 h-9">
          {TABS.map(({ key, label, icon: Icon }) => (
            <TabsTrigger key={key} value={key} className="text-xs gap-1.5">
              <Icon className="h-3.5 w-3.5" />
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="counterparties" className="mt-4">
          <CounterpartiesTab companyId={companyId} />
        </TabsContent>
        <TabsContent value="nomenclature" className="mt-4">
          <NomenclatureTab companyId={companyId} />
        </TabsContent>
        <TabsContent value="warehouses" className="mt-4">
          <WarehousesTab companyId={companyId} />
        </TabsContent>
        <TabsContent value="organizations" className="mt-4">
          <OrganizationsTab companyId={companyId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ── Универсальные подкомпоненты ─────────────────────────────

function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative">
      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Поиск по названию / коду / ИНН…"
        className="h-8 pl-8 text-xs"
      />
    </div>
  )
}

interface PagerProps {
  total: number
  offset: number
  limit: number
  isFetching: boolean
  onOffset: (offset: number) => void
}

function Pager({ total, offset, limit, isFetching, onOffset }: PagerProps) {
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(total, offset + limit)
  const canPrev = offset > 0
  const canNext = offset + limit < total
  return (
    <div className="flex items-center justify-between text-[11px] text-muted-foreground py-2 px-1">
      <div className="font-mono">
        {isFetching ? <Loader2 className="h-3 w-3 animate-spin inline" /> : null}
        {' '}{from}–{to} из {total}
      </div>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" className="h-6 px-2"
          disabled={!canPrev || isFetching}
          onClick={() => onOffset(Math.max(0, offset - limit))}>
          <ChevronLeft className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" className="h-6 px-2"
          disabled={!canNext || isFetching}
          onClick={() => onOffset(offset + limit)}>
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}

// ── Контрагенты ─────────────────────────────────────────────

function CounterpartiesTab({ companyId }: { companyId: string }) {
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, isFetching, error } = useQuery({
    queryKey: ['ref-counterparties', companyId, q, offset],
    queryFn: () => searchCounterpartiesPaged(companyId, { q, limit: PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
  })
  function onSearch(v: string) { setQ(v); setOffset(0) }

  return (
    <Card className="py-4 gap-3">
      <CardHeader className="pb-0">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">Контрагенты</CardTitle>
          <Badge variant="outline" className="text-[10px] font-mono">
            {data?.total ?? 0}
          </Badge>
        </div>
        <CardDescription className="text-xs">
          Поставщики, покупатели и прочие — для маппинга в документах.
        </CardDescription>
        <div className="mt-2">
          <SearchInput value={q} onChange={onSearch} />
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {error && <p className="text-[11px] text-destructive">{(error as Error).message}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-7 text-[10px]">Название</TableHead>
              <TableHead className="h-7 text-[10px] w-32">ИНН</TableHead>
              <TableHead className="h-7 text-[10px] w-24">КПП</TableHead>
              <TableHead className="h-7 text-[10px] w-24">Тип</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((cp: Counterparty) => (
              <TableRow key={cp.id} className="text-xs">
                <TableCell className="py-1.5">
                  <div className="font-medium">{cp.name}</div>
                  {cp.shortName && cp.shortName !== cp.name && (
                    <div className="text-[10px] text-muted-foreground">{cp.shortName}</div>
                  )}
                </TableCell>
                <TableCell className="py-1.5 font-mono text-[11px]">{cp.inn || '—'}</TableCell>
                <TableCell className="py-1.5 font-mono text-[11px]">{cp.kpp || '—'}</TableCell>
                <TableCell className="py-1.5 text-[10px] text-muted-foreground">{cp.type}</TableCell>
              </TableRow>
            ))}
            {data && data.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-[11px] text-muted-foreground py-6">
                  {q ? 'Ничего не найдено' : 'Нет данных — обновите из 1С'}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <Pager total={data?.total ?? 0} offset={offset} limit={PAGE_SIZE}
          isFetching={isFetching} onOffset={setOffset} />
      </CardContent>
    </Card>
  )
}

// ── Номенклатура ────────────────────────────────────────────

function NomenclatureTab({ companyId }: { companyId: string }) {
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, isFetching, error } = useQuery({
    queryKey: ['ref-nomenclature', companyId, q, offset],
    queryFn: () => searchNomenclaturePaged(companyId, { q, limit: PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
  })
  function onSearch(v: string) { setQ(v); setOffset(0) }

  return (
    <Card className="py-4 gap-3">
      <CardHeader className="pb-0">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">Номенклатура</CardTitle>
          <Badge variant="outline" className="text-[10px] font-mono">
            {data?.total ?? 0}
          </Badge>
        </div>
        <CardDescription className="text-xs">
          Товары и услуги — топливо, сопутка, общепит.
        </CardDescription>
        <div className="mt-2">
          <SearchInput value={q} onChange={onSearch} />
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {error && <p className="text-[11px] text-destructive">{(error as Error).message}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-7 text-[10px]">Название</TableHead>
              <TableHead className="h-7 text-[10px] w-32">Код</TableHead>
              <TableHead className="h-7 text-[10px] w-20">Ед.</TableHead>
              <TableHead className="h-7 text-[10px] w-20">НДС</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((n: Nomenclature) => (
              <TableRow key={n.id} className="text-xs">
                <TableCell className="py-1.5">{n.name}</TableCell>
                <TableCell className="py-1.5 font-mono text-[11px]">{n.code || '—'}</TableCell>
                <TableCell className="py-1.5 text-[10px]">{n.unitLabel || n.unit || '—'}</TableCell>
                <TableCell className="py-1.5 text-[10px]">{n.vatRate ?? '—'}</TableCell>
              </TableRow>
            ))}
            {data && data.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-[11px] text-muted-foreground py-6">
                  {q ? 'Ничего не найдено' : 'Нет данных — обновите из 1С'}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <Pager total={data?.total ?? 0} offset={offset} limit={PAGE_SIZE}
          isFetching={isFetching} onOffset={setOffset} />
      </CardContent>
    </Card>
  )
}

// ── Склады ──────────────────────────────────────────────────

function WarehousesTab({ companyId }: { companyId: string }) {
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, isFetching, error } = useQuery({
    queryKey: ['ref-warehouses', companyId, q, offset],
    queryFn: () => searchWarehousesPaged(companyId, { q, limit: PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
  })
  function onSearch(v: string) { setQ(v); setOffset(0) }

  return (
    <Card className="py-4 gap-3">
      <CardHeader className="pb-0">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">Склады</CardTitle>
          <Badge variant="outline" className="text-[10px] font-mono">
            {data?.total ?? 0}
          </Badge>
        </div>
        <CardDescription className="text-xs">
          АЗС, магазины, прочие места хранения.
        </CardDescription>
        <div className="mt-2">
          <SearchInput value={q} onChange={onSearch} />
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {error && <p className="text-[11px] text-destructive">{(error as Error).message}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-7 text-[10px]">Название</TableHead>
              <TableHead className="h-7 text-[10px] w-32">Код</TableHead>
              <TableHead className="h-7 text-[10px] w-32">Тип</TableHead>
              <TableHead className="h-7 text-[10px]">Адрес</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((w: Wh) => (
              <TableRow key={w.id} className="text-xs">
                <TableCell className="py-1.5">{w.name}</TableCell>
                <TableCell className="py-1.5 font-mono text-[11px]">{w.code || '—'}</TableCell>
                <TableCell className="py-1.5 text-[10px] text-muted-foreground">{w.type}</TableCell>
                <TableCell className="py-1.5 text-[10px] text-muted-foreground">{w.address || '—'}</TableCell>
              </TableRow>
            ))}
            {data && data.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-[11px] text-muted-foreground py-6">
                  {q ? 'Ничего не найдено' : 'Нет данных — обновите из 1С'}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <Pager total={data?.total ?? 0} offset={offset} limit={PAGE_SIZE}
          isFetching={isFetching} onOffset={setOffset} />
      </CardContent>
    </Card>
  )
}

// ── Организации ─────────────────────────────────────────────

function OrganizationsTab({ companyId }: { companyId: string }) {
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, isFetching, error } = useQuery({
    queryKey: ['ref-organizations', companyId, q, offset],
    queryFn: () => searchOrganizationsPaged(companyId, { q, limit: PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
  })
  function onSearch(v: string) { setQ(v); setOffset(0) }

  return (
    <Card className="py-4 gap-3">
      <CardHeader className="pb-0">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">Организации</CardTitle>
          <Badge variant="outline" className="text-[10px] font-mono">
            {data?.total ?? 0}
          </Badge>
        </div>
        <CardDescription className="text-xs">
          Юр.лица клиента — для ГИГ обычно одна с ИНН 7839440090.
        </CardDescription>
        <div className="mt-2">
          <SearchInput value={q} onChange={onSearch} />
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {error && <p className="text-[11px] text-destructive">{(error as Error).message}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="h-7 text-[10px]">Название</TableHead>
              <TableHead className="h-7 text-[10px] w-32">ИНН</TableHead>
              <TableHead className="h-7 text-[10px] w-24">КПП</TableHead>
              <TableHead className="h-7 text-[10px] w-28">ОГРН</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((o: Organization) => (
              <TableRow key={o.id} className="text-xs">
                <TableCell className="py-1.5">{o.name}</TableCell>
                <TableCell className="py-1.5 font-mono text-[11px]">{o.inn || '—'}</TableCell>
                <TableCell className="py-1.5 font-mono text-[11px]">{o.kpp || '—'}</TableCell>
                <TableCell className="py-1.5 font-mono text-[11px]">{o.ogrn || '—'}</TableCell>
              </TableRow>
            ))}
            {data && data.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-[11px] text-muted-foreground py-6">
                  {q ? 'Ничего не найдено' : 'Нет данных — обновите из 1С'}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <Pager total={data?.total ?? 0} offset={offset} limit={PAGE_SIZE}
          isFetching={isFetching} onOffset={setOffset} />
      </CardContent>
    </Card>
  )
}
