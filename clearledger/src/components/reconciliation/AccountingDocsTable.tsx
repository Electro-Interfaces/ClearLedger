/**
 * Таблица учётных документов 1С с фильтрацией и статусом сверки.
 */

import { useState, useMemo } from 'react'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Search, Trash2, Unlink } from 'lucide-react'
import type { AccountingDoc } from '@/types'
import { DOC_TYPE_LABELS, MATCH_STATUS_CONFIG } from '@/config/statuses'

interface Props {
  docs: AccountingDoc[]
  onDelete?: (id: string) => void
  onUnmatch?: (id: string) => void
  onSelect?: (doc: AccountingDoc) => void
}

export function AccountingDocsTable({ docs, onDelete, onUnmatch, onSelect }: Props) {
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search) return docs
    const q = search.toLowerCase()
    return docs.filter(
      (d) =>
        d.number.toLowerCase().includes(q) ||
        d.counterpartyName.toLowerCase().includes(q) ||
        (d.counterpartyInn || '').includes(q),
    )
  }, [docs, search])

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          placeholder="Поиск по номеру, контрагенту, ИНН..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Тип</TableHead>
              <TableHead>Номер</TableHead>
              <TableHead className="w-[100px]">Дата</TableHead>
              <TableHead>Контрагент</TableHead>
              <TableHead className="w-[130px] text-right">Сумма</TableHead>
              <TableHead className="w-[110px]">Статус 1С</TableHead>
              <TableHead className="w-[130px]">Сверка</TableHead>
              <TableHead className="w-[80px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground h-24">
                  {docs.length === 0 ? 'Нет документов' : 'Ничего не найдено'}
                </TableCell>
              </TableRow>
            )}
            {filtered.map((d) => {
              const matchInfo = MATCH_STATUS_CONFIG[d.matchStatus] || MATCH_STATUS_CONFIG.pending
              return (
                <TableRow
                  key={d.id}
                  className={onSelect ? 'cursor-pointer hover:bg-muted/50' : ''}
                  onClick={() => onSelect?.(d)}
                >
                  <TableCell>
                    <Badge variant="outline" className="text-xs">
                      {DOC_TYPE_LABELS[d.docType] || d.docType}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-sm">{d.number}</TableCell>
                  <TableCell className="text-sm">{d.date}</TableCell>
                  <TableCell>
                    <div className="font-medium text-sm">{d.counterpartyName}</div>
                    {d.counterpartyInn && (
                      <div className="text-xs text-muted-foreground">ИНН {d.counterpartyInn}</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {d.amount.toLocaleString('ru-RU', { minimumFractionDigits: 2 })}
                  </TableCell>
                  <TableCell>
                    <Badge variant={d.status1c === 'Проведён' ? 'default' : 'secondary'} className="text-xs">
                      {d.status1c}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={matchInfo.variant} className="text-xs">
                      {matchInfo.label}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                      {d.matchStatus === 'matched' && onUnmatch && (
                        <Button variant="ghost" size="icon" className="size-7" onClick={() => onUnmatch(d.id)} title="Разорвать связь">
                          <Unlink className="size-3.5" />
                        </Button>
                      )}
                      {onDelete && (
                        <Button variant="ghost" size="icon" className="size-7" onClick={() => onDelete(d.id)}>
                          <Trash2 className="size-3.5" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">Показано {filtered.length} из {docs.length}</p>
    </div>
  )
}
