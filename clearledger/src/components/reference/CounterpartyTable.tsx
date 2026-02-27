/**
 * Таблица контрагентов с поиском.
 */

import { useState, useMemo } from 'react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Trash2, Search } from 'lucide-react'
import type { Counterparty } from '@/types'

interface CounterpartyTableProps {
  data: Counterparty[]
  onDelete?: (id: string) => void
}

const TYPE_COLORS: Record<string, string> = {
  'ЮЛ': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  'ИП': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  'ФЛ': 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200',
}

export function CounterpartyTable({ data, onDelete }: CounterpartyTableProps) {
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search) return data
    const q = search.toLowerCase()
    return data.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.inn.includes(q) ||
        (c.shortName && c.shortName.toLowerCase().includes(q)) ||
        c.aliases.some((a) => a.toLowerCase().includes(q)),
    )
  }, [data, search])

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          placeholder="Поиск по имени или ИНН..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[300px]">Наименование</TableHead>
              <TableHead className="w-[120px]">ИНН</TableHead>
              <TableHead className="w-[100px]">КПП</TableHead>
              <TableHead className="w-[60px]">Тип</TableHead>
              <TableHead>Алиасы</TableHead>
              {onDelete && <TableHead className="w-[50px]" />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={onDelete ? 6 : 5} className="text-center text-muted-foreground h-24">
                  {data.length === 0 ? 'Справочник пуст. Импортируйте данные из 1С.' : 'Ничего не найдено'}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((cp) => (
              <TableRow key={cp.id}>
                <TableCell>
                  <div className="font-medium">{cp.name}</div>
                  {cp.shortName && cp.shortName !== cp.name && (
                    <div className="text-xs text-muted-foreground">{cp.shortName}</div>
                  )}
                </TableCell>
                <TableCell className="font-mono text-sm">{cp.inn}</TableCell>
                <TableCell className="font-mono text-sm">{cp.kpp || '—'}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={TYPE_COLORS[cp.type] || ''}>
                    {cp.type}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {cp.aliases.slice(0, 3).map((a, i) => (
                      <Badge key={i} variant="secondary" className="text-xs">
                        {a}
                      </Badge>
                    ))}
                    {cp.aliases.length > 3 && (
                      <Badge variant="secondary" className="text-xs">
                        +{cp.aliases.length - 3}
                      </Badge>
                    )}
                  </div>
                </TableCell>
                {onDelete && (
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      onClick={() => onDelete(cp.id)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <p className="text-xs text-muted-foreground">
        Показано {filtered.length} из {data.length}
      </p>
    </div>
  )
}
