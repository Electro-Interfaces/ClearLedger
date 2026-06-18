/**
 * «Контрагенты» (раздел «Загрузка») — разрез контрагентов и их договоров (ось
 * контрагент↔договор↔точки/разрезы). Мастер-деталь: слева список контрагентов,
 * справа — выбранный контрагент, где он работает и его договоры с охватом.
 */
import { useState, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Search, Building2, MapPin, Loader2 } from 'lucide-react'
import { useCounterparties, useContracts, useCounterpartyLocations } from '@/hooks/useReferences'
import { ContractScopeDialog, ContractScopeBadgeLabel } from '@/components/reference/ContractScopeDialog'
import type { Counterparty } from '@/types'

const TYPE_COLOR: Record<string, string> = {
  'ЮЛ': 'bg-blue-500/10 text-blue-600 dark:text-blue-400',
  'ИП': 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  'ФЛ': 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400',
}

function WhereWorks({ counterpartyId }: { counterpartyId: string }) {
  const { data, isLoading } = useCounterpartyLocations(counterpartyId)
  if (isLoading) return <Loader2 className="size-4 animate-spin text-muted-foreground" />
  if (!data) return null
  return (
    <div className="flex items-center gap-2 flex-wrap text-sm">
      <MapPin className="size-4 text-muted-foreground shrink-0" />
      {data.scope === 'company' && <Badge variant="secondary">Вся компания</Badge>}
      {data.scope === 'locations' && data.locations.map((l) => (
        <Badge key={l.id} variant="outline">{l.name}</Badge>
      ))}
      {data.scope === 'none' && <span className="text-xs text-muted-foreground">точки не заданы</span>}
      {data.unassignedCount > 0 && (
        <span className="text-xs text-amber-600 dark:text-amber-400">
          · нераспределённых договоров: {data.unassignedCount}
        </span>
      )}
    </div>
  )
}

function ContractorDetail({ cp }: { cp: Counterparty }) {
  const { data: allContracts = [] } = useContracts()
  // Договоры из 1С хранят counterpartyId = GUID (externalRef); ручные — наш id.
  const contracts = useMemo(
    () => allContracts.filter(
      (c) => c.counterpartyId === cp.externalRef || c.counterpartyId === cp.id,
    ),
    [allContracts, cp.externalRef, cp.id],
  )

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2 flex-wrap">
          <Building2 className="size-5 text-muted-foreground" />
          <h2 className="text-lg font-semibold">{cp.name}</h2>
          <Badge variant="outline" className={TYPE_COLOR[cp.type] || ''}>{cp.type}</Badge>
        </div>
        <div className="text-sm text-muted-foreground mt-1">
          ИНН {cp.inn}{cp.kpp && <span> · КПП {cp.kpp}</span>}
          {cp.fullName && cp.fullName !== cp.name && <span> · {cp.fullName}</span>}
        </div>
        <div className="mt-2">
          <WhereWorks counterpartyId={cp.id} />
        </div>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[140px]">Номер</TableHead>
              <TableHead className="w-[100px]">Дата</TableHead>
              <TableHead>Вид</TableHead>
              <TableHead className="w-[160px]">Охват</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {contracts.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground h-20">
                  У контрагента нет договоров
                </TableCell>
              </TableRow>
            )}
            {contracts.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-mono text-sm">{c.number}</TableCell>
                <TableCell className="text-sm">{c.date || '—'}</TableCell>
                <TableCell className="text-sm">{c.kind || c.type || '—'}</TableCell>
                <TableCell>
                  <ContractScopeDialog contract={c}>
                    <Button variant="ghost" size="sm" className="h-7 -ml-2 gap-1.5 font-normal">
                      <MapPin className="size-3.5 text-muted-foreground shrink-0" />
                      <Badge
                        variant={c.scopeType === 'company' ? 'secondary' : 'outline'}
                        className={c.scopeType === 'unassigned' || !c.scopeType ? 'text-muted-foreground' : ''}
                      >
                        {ContractScopeBadgeLabel(c.scopeType)}
                      </Badge>
                    </Button>
                  </ContractScopeDialog>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

export function ContractorsPage() {
  const { data: counterparties = [], isLoading } = useCounterparties()
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return counterparties
    return counterparties.filter(
      (c) => c.name.toLowerCase().includes(q) || c.inn.includes(q),
    )
  }, [counterparties, search])

  const selected = counterparties.find((c) => c.id === selectedId) ?? null

  return (
    <div className="flex-1 min-w-0 p-4 lg:p-6">
      <div className="mb-4">
        <h1 className="text-xl font-semibold">Контрагенты и договоры</h1>
        <p className="text-sm text-muted-foreground">
          Разрез по контрагентам: их договоры, охват точек и ограничения по разрезам.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4">
        {/* Список контрагентов */}
        <Card className="lg:h-[calc(100vh-12rem)] flex flex-col">
          <CardContent className="p-3 flex flex-col gap-3 min-h-0">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
              <Input placeholder="Поиск по имени или ИНН..." value={search}
                onChange={(e) => setSearch(e.target.value)} className="pl-8 h-9" />
            </div>
            <div className="overflow-y-auto space-y-0.5 min-h-0">
              {isLoading && <div className="text-sm text-muted-foreground p-2">Загрузка…</div>}
              {!isLoading && filtered.length === 0 && (
                <div className="text-sm text-muted-foreground p-2">Контрагенты не найдены.</div>
              )}
              {filtered.slice(0, 300).map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelectedId(c.id)}
                  className={`w-full text-left px-2.5 py-1.5 rounded-md text-sm transition-colors ${
                    c.id === selectedId ? 'bg-accent' : 'hover:bg-muted'
                  }`}
                >
                  <div className="font-medium truncate">{c.name}</div>
                  <div className="text-xs text-muted-foreground">ИНН {c.inn}</div>
                </button>
              ))}
              {filtered.length > 300 && (
                <div className="text-[11px] text-muted-foreground p-2">
                  …показаны первые 300, уточните поиском ({filtered.length} всего)
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Детали выбранного контрагента */}
        <Card className="lg:h-[calc(100vh-12rem)] overflow-y-auto">
          <CardContent className="p-4">
            {selected
              ? <ContractorDetail cp={selected} />
              : (
                <div className="h-full flex items-center justify-center text-sm text-muted-foreground py-20">
                  Выберите контрагента слева
                </div>
              )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
