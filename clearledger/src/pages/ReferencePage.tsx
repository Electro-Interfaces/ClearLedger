/**
 * Страница "Справочники" — табы: Контрагенты | Организации | Номенклатура | Договоры.
 */

import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Upload, Users, Building2, Package, FileSignature, Trash2, Search } from 'lucide-react'
import { CounterpartyTable } from '@/components/reference/CounterpartyTable'
import { ImportDialog } from '@/components/reference/ImportDialog'
import {
  useCounterparties, useOrganizations, useNomenclature, useContracts,
  useDeleteCounterparty, useDeleteOrganization, useDeleteNomenclature, useDeleteContract,
  useReferenceStats,
} from '@/hooks/useReferences'
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
