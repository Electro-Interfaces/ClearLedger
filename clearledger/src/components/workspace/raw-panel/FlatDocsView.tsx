/**
 * «Документы» списком: все документы одной таблицей, без папок.
 *
 * Дерево отвечает на вопрос «что где лежит», а работа идёт от вопроса «покажи все
 * неоплаченные счета за прошлый квартал» — по дереву такой отбор собирается руками
 * из десятка папок. Поэтому второй режим: тот же набор, но плоско и с отбором.
 *
 * Фильтрует ЗДЕСЬ, а не на сервере: набор уже целиком в памяти (проводник строит по
 * нему дерево), и лишний круг к API только добавил бы задержку на каждое нажатие.
 */
import { useMemo, useState } from 'react'
import { Search, X } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { DocRow } from '@/services/booksService'
import type { FsNode, SortConfig } from './raw-panel-types'

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

function ru(date?: string | null) {
  return date ? date.slice(0, 10).split('-').reverse().join('.') : '—'
}

const SECTION_LABEL: Record<string, string> = {
  sales: 'Продажи', purchases: 'Закупки', money: 'Деньги',
  warehouse: 'Склад', closing: 'Закрытие периода',
}

type Paid = 'all' | 'paid' | 'unpaid'

interface Filters {
  q: string
  from: string
  to: string
  type: string
  section: string
  status: string
  paid: Paid
}

const EMPTY: Filters = { q: '', from: '', to: '', type: 'all', section: 'all', status: 'all', paid: 'all' }

function Select({ value, onChange, items, title }: {
  value: string; onChange: (v: string) => void
  items: { value: string; label: string }[]; title: string
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} title={title}
      className="h-8 max-w-[220px] rounded-md border border-border bg-background/70 px-2 text-[13px] outline-none">
      {items.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
    </select>
  )
}

export function FlatDocsView({ files, sortConfig, onSort, onOpen }: {
  files: FsNode[]
  sortConfig: SortConfig
  onSort: (c: SortConfig['column']) => void
  onOpen: (node: FsNode) => void
}) {
  const [f, setF] = useState<Filters>(EMPTY)
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setF((p) => ({ ...p, [k]: v }))

  // Строка реестра лежит в узле — она и есть источник всех колонок и отборов.
  const rows = useMemo(() => files.map((n) => ({ node: n, doc: n.doc?.data as DocRow | undefined }))
    .filter((r) => !!r.doc), [files])

  const types = useMemo(() => {
    const seen = new Map<string, string>()
    for (const r of rows) if (r.doc && !seen.has(r.doc.type)) seen.set(r.doc.type, r.doc.label)
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1], 'ru'))
  }, [rows])

  const sections = useMemo(() => {
    const seen = new Set<string>()
    for (const r of rows) if (r.doc?.section) seen.add(r.doc.section)
    return [...seen]
  }, [rows])

  const statuses = useMemo(() => {
    const seen = new Set<string>()
    for (const r of rows) if (r.doc?.status) seen.add(r.doc.status)
    return [...seen]
  }, [rows])

  const filtered = useMemo(() => {
    const q = f.q.trim().toLowerCase()
    return rows.filter(({ doc }) => {
      if (!doc) return false
      if (f.type !== 'all' && doc.type !== f.type) return false
      if (f.section !== 'all' && doc.section !== f.section) return false
      if (f.status !== 'all' && doc.status !== f.status) return false
      if (f.from && (doc.date || '') < f.from) return false
      if (f.to && (doc.date || '') > f.to) return false
      // Оплата спрашивается только у счетов покупателям — у прочих поле не заполняется.
      if (f.paid !== 'all') {
        if (doc.paid === null || doc.paid === undefined) return false
        if (f.paid === 'paid' && doc.paid <= 0) return false
        if (f.paid === 'unpaid' && doc.paid > 0) return false
      }
      if (q) {
        const hay = `${doc.number} ${doc.counterparty} ${doc.inn ?? ''} ${doc.label} ${doc.operation ?? ''}`
        if (!hay.toLowerCase().includes(q)) return false
      }
      return true
    })
  }, [rows, f])

  const sorted = useMemo(() => {
    const dir = sortConfig.direction === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const x = a.doc!, y = b.doc!
      switch (sortConfig.column) {
        case 'name': return dir * (x.counterparty || '').localeCompare(y.counterparty || '', 'ru')
        case 'status': return dir * (x.status || '').localeCompare(y.status || '', 'ru')
        default: return dir * (x.date || '').localeCompare(y.date || '')
      }
    })
  }, [filtered, sortConfig])

  const total = filtered.reduce((s, r) => s + (r.doc?.amount ?? 0), 0)
  const vat = filtered.reduce((s, r) => s + (r.doc?.vat ?? 0), 0)
  const dirty = JSON.stringify(f) !== JSON.stringify(EMPTY)

  const Th = ({ children, right, col }: {
    children: React.ReactNode; right?: boolean; col?: SortConfig['column']
  }) => (
    <th className={cn('font-normal px-3 py-2 whitespace-nowrap', right ? 'text-right' : 'text-left',
      col && 'cursor-pointer select-none hover:text-foreground')}
      onClick={col ? () => onSort(col) : undefined}>
      {children}
      {col && sortConfig.column === col && (
        <span className="ml-1 opacity-60">{sortConfig.direction === 'asc' ? '↑' : '↓'}</span>
      )}
    </th>
  )

  return (
    <div className="flex-1 min-w-0 flex flex-col bg-background">
      {/* Панель отбора */}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-border bg-card/40">
        <div className="flex items-center gap-1.5 h-8 w-56 px-2.5 rounded-md bg-background/70 border border-border">
          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <input value={f.q} onChange={(e) => set('q', e.target.value)}
            placeholder="Номер, контрагент, ИНН, назначение"
            className="bg-transparent outline-none text-[13px] w-full placeholder:text-muted-foreground/60" />
        </div>
        <Select title="Участок учёта" value={f.section} onChange={(v) => set('section', v)}
          items={[{ value: 'all', label: 'Все участки' },
            ...sections.map((s) => ({ value: s, label: SECTION_LABEL[s] ?? s }))]} />
        <Select title="Вид документа" value={f.type} onChange={(v) => set('type', v)}
          items={[{ value: 'all', label: 'Все виды' },
            ...types.map(([v, label]) => ({ value: v, label }))]} />
        <Select title="Статус в 1С" value={f.status} onChange={(v) => set('status', v)}
          items={[{ value: 'all', label: 'Любой статус' },
            ...statuses.map((s) => ({ value: s, label: s }))]} />
        <Select title="Оплата — только у счетов покупателям" value={f.paid}
          onChange={(v) => set('paid', v as Paid)}
          items={[{ value: 'all', label: 'Оплата: неважно' },
            { value: 'paid', label: 'Оплаченные счета' },
            { value: 'unpaid', label: 'Неоплаченные счета' }]} />
        <div className="flex items-center gap-1 text-[13px]">
          <input type="date" value={f.from} onChange={(e) => set('from', e.target.value)}
            className="h-8 rounded-md border border-border bg-background/70 px-2 outline-none" />
          <span className="text-muted-foreground">—</span>
          <input type="date" value={f.to} onChange={(e) => set('to', e.target.value)}
            className="h-8 rounded-md border border-border bg-background/70 px-2 outline-none" />
        </div>
        {dirty && (
          <button onClick={() => setF(EMPTY)}
            className="inline-flex items-center gap-1 h-8 px-2 rounded-md text-[13px] text-muted-foreground hover:bg-accent">
            <X className="h-3.5 w-3.5" /> Сбросить
          </button>
        )}
      </div>

      {/* Итог отбора — рядом с таблицей, а не в статус-баре: он и есть ответ на отбор */}
      <div className="px-3 py-1.5 text-[11px] text-muted-foreground border-b border-border">
        Отобрано {sorted.length} из {rows.length} · сумма {money.format(total)} ₽
        {vat > 0 && <> · в т.ч. НДС {money.format(vat)} ₽</>}
      </div>

      <div className="flex-1 min-h-0 overflow-auto scroll-thin">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-card text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr className="border-b border-border">
              <Th col="date">Дата</Th>
              <Th>Вид</Th>
              <Th>Номер</Th>
              <Th col="name">Контрагент</Th>
              <Th>Назначение</Th>
              <Th right>Сумма</Th>
              <Th right>НДС</Th>
              <Th col="status">Статус</Th>
              <Th right>Оплачено</Th>
              <Th right>Строк</Th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr><td colSpan={10} className="px-3 py-10 text-center text-muted-foreground">
                Под отбор ничего не попало.
              </td></tr>
            )}
            {sorted.map(({ node, doc }) => (
              <tr key={node.path} onClick={() => onOpen(node)}
                className="border-b border-border/60 last:border-0 hover:bg-accent/40 cursor-pointer">
                <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">
                  {ru(doc!.date)}
                  {doc!.periodStatus === 'closed' && (
                    <span className="ml-1.5 text-[10px] text-muted-foreground" title="период закрыт">🔒</span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{doc!.label}</td>
                <td className="px-3 py-1.5 tabular-nums">{doc!.number || 'б/н'}</td>
                <td className="px-3 py-1.5 max-w-[240px] truncate" title={doc!.counterparty}>
                  {doc!.counterparty || '—'}
                </td>
                <td className="px-3 py-1.5 max-w-[260px] truncate text-muted-foreground"
                  title={doc!.operation ?? ''}>{doc!.operation || '—'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{money.format(doc!.amount)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                  {doc!.vat ? money.format(doc!.vat) : '—'}
                </td>
                <td className={cn('px-3 py-1.5 whitespace-nowrap',
                  doc!.status !== 'Проведён' && 'text-amber-600')}>{doc!.status}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {doc!.paid === null || doc!.paid === undefined ? '—'
                    : doc!.paid > 0 ? money.format(doc!.paid)
                    : <span className="text-muted-foreground">не оплачен</span>}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                  {doc!.lines || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
