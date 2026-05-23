/**
 * Страница "Справочники" — табы: Контрагенты | Организации | Номенклатура | Договоры | Склады | Банк. счета | Документы 1С.
 */

import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Upload, Users, Building2, Package, FileSignature, Trash2, Search, Warehouse as WarehouseIcon, Landmark, FileText } from 'lucide-react'
import { CounterpartyTable } from '@/components/reference/CounterpartyTable'
import { ImportDialog } from '@/components/reference/ImportDialog'
import { AccountingDocsTab } from '@/components/reference/AccountingDocsTab'
import {
  useCounterparties, useOrganizations, useNomenclature, useContracts,
  useWarehouses, useBankAccounts,
  useDeleteCounterparty, useDeleteOrganization, useDeleteNomenclature, useDeleteContract,
  useDeleteWarehouse, useDeleteBankAccount,
  useReferenceStats,
} from '@/hooks/useReferences'
import { useAccountingDocs } from '@/hooks/useAccountingDocs'
import { useMemo } from 'react'

export function ReferencePage() {
  const [importOpen, setImportOpen] = useState(false)
  const { data: stats } = useReferenceStats()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Справочники</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Эталонные данные из 1С:Бухгалтерия для сверки входящих документов
          </p>
        </div>
        <Button onClick={() => setImportOpen(true)}>
          <Upload className="size-4 mr-2" />
          Импорт из 1С
        </Button>
      </div>

      <Tabs defaultValue="counterparties">
        <TabsList>
          <TabsTrigger value="counterparties" className="gap-1.5">
            <Users className="size-4" />
            Контрагенты
            {stats && stats.counterparties > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{stats.counterparties}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="organizations" className="gap-1.5">
            <Building2 className="size-4" />
            Организации
            {stats && stats.organizations > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{stats.organizations}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="nomenclature" className="gap-1.5">
            <Package className="size-4" />
            Номенклатура
            {stats && stats.nomenclature > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{stats.nomenclature}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="contracts" className="gap-1.5">
            <FileSignature className="size-4" />
            Договоры
            {stats && stats.contracts > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{stats.contracts}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="warehouses" className="gap-1.5">
            <WarehouseIcon className="size-4" />
            Склады
            {stats && stats.warehouses > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{stats.warehouses}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="bank-accounts" className="gap-1.5">
            <Landmark className="size-4" />
            Банк. счета
            {stats && stats.bankAccounts > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{stats.bankAccounts}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="accounting-docs" className="gap-1.5">
            <FileText className="size-4" />
            Документы 1С
            <AccDocsCountBadge />
          </TabsTrigger>
        </TabsList>

        <TabsContent value="counterparties" className="mt-4">
          <CounterpartiesTab />
        </TabsContent>
        <TabsContent value="organizations" className="mt-4">
          <OrganizationsTab />
        </TabsContent>
        <TabsContent value="nomenclature" className="mt-4">
          <NomenclatureTab />
        </TabsContent>
        <TabsContent value="contracts" className="mt-4">
          <ContractsTab />
        </TabsContent>
        <TabsContent value="warehouses" className="mt-4">
          <WarehousesTab />
        </TabsContent>
        <TabsContent value="bank-accounts" className="mt-4">
          <BankAccountsTab />
        </TabsContent>
        <TabsContent value="accounting-docs" className="mt-4">
          <AccountingDocsTab />
        </TabsContent>
      </Tabs>

      <ImportDialog open={importOpen} onOpenChange={setImportOpen} />
    </div>
  )
}

// ---- Вкладка "Контрагенты" ----

function CounterpartiesTab() {
  const { data = [], isLoading } = useCounterparties()
  const deleteMut = useDeleteCounterparty()

  if (isLoading) return <TableSkeleton />

  return (
    <CounterpartyTable
      data={data}
      onDelete={(id) => deleteMut.mutate(id)}
    />
  )
}

// ---- Вкладка "Организации" ----

function OrganizationsTab() {
  const { data = [], isLoading } = useOrganizations()
  const deleteMut = useDeleteOrganization()
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search) return data
    const q = search.toLowerCase()
    return data.filter(
      (o) => o.name.toLowerCase().includes(q) || o.inn.includes(q),
    )
  }, [data, search])

  if (isLoading) return <TableSkeleton />

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input placeholder="Поиск..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Наименование</TableHead>
              <TableHead className="w-[120px]">ИНН</TableHead>
              <TableHead className="w-[100px]">КПП</TableHead>
              <TableHead className="w-[130px]">ОГРН</TableHead>
              <TableHead>Р/С</TableHead>
              <TableHead className="w-[100px]">БИК</TableHead>
              <TableHead className="w-[50px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground h-24">
                  {data.length === 0 ? 'Справочник пуст' : 'Ничего не найдено'}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((o) => (
              <TableRow key={o.id}>
                <TableCell className="font-medium">{o.name}</TableCell>
                <TableCell className="font-mono text-sm">{o.inn}</TableCell>
                <TableCell className="font-mono text-sm">{o.kpp || '—'}</TableCell>
                <TableCell className="font-mono text-sm">{o.ogrn || '—'}</TableCell>
                <TableCell className="font-mono text-sm">{o.bankAccount || '—'}</TableCell>
                <TableCell className="font-mono text-sm">{o.bankBik || '—'}</TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon" className="size-7" onClick={() => deleteMut.mutate(o.id)}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">Показано {filtered.length} из {data.length}</p>
    </div>
  )
}

// ---- Вкладка "Номенклатура" ----

function NomenclatureTab() {
  const { data = [], isLoading } = useNomenclature()
  const deleteMut = useDeleteNomenclature()
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search) return data
    const q = search.toLowerCase()
    return data.filter(
      (n) => n.name.toLowerCase().includes(q) || n.code.toLowerCase().includes(q),
    )
  }, [data, search])

  if (isLoading) return <TableSkeleton />

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input placeholder="Поиск..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[100px]">Код</TableHead>
              <TableHead>Наименование</TableHead>
              <TableHead className="w-[80px]">Ед. изм.</TableHead>
              <TableHead className="w-[80px]">НДС</TableHead>
              <TableHead className="w-[50px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground h-24">
                  {data.length === 0 ? 'Справочник пуст' : 'Ничего не найдено'}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((n) => (
              <TableRow key={n.id}>
                <TableCell className="font-mono text-sm">{n.code}</TableCell>
                <TableCell className="font-medium">{n.name}</TableCell>
                <TableCell>{n.unitLabel}</TableCell>
                <TableCell>{n.vatRate}%</TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon" className="size-7" onClick={() => deleteMut.mutate(n.id)}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">Показано {filtered.length} из {data.length}</p>
    </div>
  )
}

// ---- Вкладка "Договоры" ----

function ContractsTab() {
  const { data = [], isLoading } = useContracts()
  const { data: counterparties = [] } = useCounterparties()
  const { data: organizations = [] } = useOrganizations()
  const deleteMut = useDeleteContract()
  const [search, setSearch] = useState('')

  const cpMap = useMemo(() => new Map(counterparties.map((c) => [c.id, c.name])), [counterparties])
  const orgMap = useMemo(() => new Map(organizations.map((o) => [o.id, o.name])), [organizations])

  const filtered = useMemo(() => {
    if (!search) return data
    const q = search.toLowerCase()
    return data.filter(
      (c) =>
        c.number.toLowerCase().includes(q) ||
        c.type.toLowerCase().includes(q) ||
        (cpMap.get(c.counterpartyId) || '').toLowerCase().includes(q),
    )
  }, [data, search, cpMap])

  if (isLoading) return <TableSkeleton />

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input placeholder="Поиск..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[120px]">Номер</TableHead>
              <TableHead className="w-[100px]">Дата</TableHead>
              <TableHead>Контрагент</TableHead>
              <TableHead>Организация</TableHead>
              <TableHead className="w-[100px]">Тип</TableHead>
              <TableHead className="w-[120px]">Лимит</TableHead>
              <TableHead className="w-[50px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground h-24">
                  {data.length === 0 ? 'Справочник пуст' : 'Ничего не найдено'}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-mono text-sm">{c.number}</TableCell>
                <TableCell className="text-sm">{c.date || '—'}</TableCell>
                <TableCell>{cpMap.get(c.counterpartyId) || c.counterpartyId || '—'}</TableCell>
                <TableCell>{orgMap.get(c.organizationId) || c.organizationId || '—'}</TableCell>
                <TableCell>
                  <Badge variant="outline">{c.type}</Badge>
                </TableCell>
                <TableCell className="font-mono text-sm">
                  {c.amountLimit != null ? c.amountLimit.toLocaleString('ru-RU') : '—'}
                </TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon" className="size-7" onClick={() => deleteMut.mutate(c.id)}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">Показано {filtered.length} из {data.length}</p>
    </div>
  )
}

// ---- Badge для количества документов 1С ----

function AccDocsCountBadge() {
  const { data = [] } = useAccountingDocs()
  if (data.length === 0) return null
  return <Badge variant="secondary" className="ml-1 text-xs">{data.length}</Badge>
}

// ---- Вкладка "Склады" ----

function WarehousesTab() {
  const { data = [], isLoading } = useWarehouses()
  const deleteMut = useDeleteWarehouse()
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search) return data
    const q = search.toLowerCase()
    return data.filter(
      (w) => w.name.toLowerCase().includes(q) || w.code.toLowerCase().includes(q),
    )
  }, [data, search])

  if (isLoading) return <TableSkeleton />

  const typeLabels: Record<string, string> = {
    warehouse: 'Склад',
    station: 'АЗС',
    office: 'Офис',
    other: 'Прочее',
  }

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input placeholder="Поиск..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[100px]">Код</TableHead>
              <TableHead>Наименование</TableHead>
              <TableHead>Адрес</TableHead>
              <TableHead className="w-[80px]">Тип</TableHead>
              <TableHead className="w-[50px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground h-24">
                  {data.length === 0 ? 'Справочник пуст' : 'Ничего не найдено'}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((w) => (
              <TableRow key={w.id}>
                <TableCell className="font-mono text-sm">{w.code}</TableCell>
                <TableCell className="font-medium">{w.name}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{w.address || '—'}</TableCell>
                <TableCell>
                  <Badge variant="outline">{typeLabels[w.type] || w.type}</Badge>
                </TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon" className="size-7" onClick={() => deleteMut.mutate(w.id)}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">Показано {filtered.length} из {data.length}</p>
    </div>
  )
}

// ---- Вкладка "Банковские счета" ----

function BankAccountsTab() {
  const { data = [], isLoading } = useBankAccounts()
  const deleteMut = useDeleteBankAccount()
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search) return data
    const q = search.toLowerCase()
    return data.filter(
      (b) =>
        b.number.includes(q) ||
        b.bankName.toLowerCase().includes(q) ||
        b.bik.includes(q),
    )
  }, [data, search])

  if (isLoading) return <TableSkeleton />

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input placeholder="Поиск..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Номер счёта</TableHead>
              <TableHead>Банк</TableHead>
              <TableHead className="w-[100px]">БИК</TableHead>
              <TableHead>Корр. счёт</TableHead>
              <TableHead className="w-[60px]">Валюта</TableHead>
              <TableHead className="w-[50px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground h-24">
                  {data.length === 0 ? 'Справочник пуст' : 'Ничего не найдено'}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((b) => (
              <TableRow key={b.id}>
                <TableCell className="font-mono text-sm">{b.number}</TableCell>
                <TableCell className="font-medium">{b.bankName}</TableCell>
                <TableCell className="font-mono text-sm">{b.bik}</TableCell>
                <TableCell className="font-mono text-sm">{b.corrAccount || '—'}</TableCell>
                <TableCell>{b.currency}</TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon" className="size-7" onClick={() => deleteMut.mutate(b.id)}>
                    <Trash2 className="size-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">Показано {filtered.length} из {data.length}</p>
    </div>
  )
}

// ---- Скелетон ----

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-12 bg-muted/50 rounded animate-pulse" />
      ))}
    </div>
  )
}
