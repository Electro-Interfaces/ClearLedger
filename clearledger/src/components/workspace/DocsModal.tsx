/**
 * Расшифровка документа (или пачки документов) — один вид окна на весь «Магазин».
 *
 * Строки рисует `DocLines`: разметка выводится из полей самой строки, поэтому приход,
 * инвентаризация, списание и переоценка обходятся одним рендером. Раньше он жил внутри
 * `ShiftDetailModal`, из-за чего документные панели заводили свои копии, а Приёмка и
 * Поставщики не раскрывались вовсе.
 *
 * Один документ = `docs` длиной 1 (строки видны сразу). Пачка — аккордеон: так
 * расшифровывается поставщик (его накладные за период).
 */
import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { ShiftDocLine } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number | null | undefined) => (n == null ? '—' : fmtMoney(n))

export interface DocForDrill { number: string | null; lines: ShiftDocLine[]; meta?: string }

/** Строки документа — рендер по наличию полей (приход/инвент/списание/переоценка). */
export function DocLines({ lines, onOpenSku }: { lines: ShiftDocLine[]; onOpenSku?: (guid: string) => void }) {
  if (!lines?.length) return <div className="px-3 py-1.5 text-[11px] text-muted-foreground">Строк в документе нет</div>
  const isReval = lines.some((l) => l.old != null || l.new != null)
  const isInv = lines.some((l) => l.fact != null || l.uchet != null)
  return (
    <table className="w-full text-[11px]">
      <tbody>
        {lines.map((l, i) => {
          const ref = l.ref
          const open = onOpenSku && ref ? () => onOpenSku(ref) : null
          return (
            <tr key={i} className={`border-t border-border/20 ${open ? 'cursor-pointer hover:bg-accent/20' : ''}`}
              {...(open ? { tabIndex: 0, onClick: open, onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open() } } } : {})}>
              <td className="px-3 py-1">{l.name ?? '—'}</td>
              {isReval ? (
                <td className="px-3 py-1 text-right tabular-nums whitespace-nowrap">
                  {money(l.old)} → {money(l.new)}
                  {l.pct != null && <span className={`ml-1 ${(l.pct ?? 0) < 0 ? 'text-emerald-300/80' : 'text-amber-300/80'}`}>{l.pct > 0 ? '+' : ''}{nf(l.pct, 1)}%</span>}
                </td>
              ) : isInv ? (
                <td className="px-3 py-1 text-right tabular-nums whitespace-nowrap">
                  факт {nf(l.fact ?? 0, 2)} / учёт {nf(l.uchet ?? 0, 2)}
                  <span className={`ml-1 ${(l.dev ?? 0) < 0 ? 'text-red-400/80' : 'text-emerald-300/80'}`}>({(l.dev ?? 0) >= 0 ? '+' : ''}{nf(l.dev ?? 0, 2)})</span>
                  {l.amount != null && <span className="ml-1 text-muted-foreground">{money(l.amount)}</span>}
                </td>
              ) : (
                <td className="px-3 py-1 text-right tabular-nums whitespace-nowrap">
                  {l.qty != null ? nf(l.qty, 3) : '—'}{l.price != null ? ` × ${money(l.price)}` : ''}{l.amount != null ? ` = ${money(l.amount)}` : ''}
                </td>
              )}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** Список документов с раскрытием строк — тело и смены, и модалки поставщика. */
export function DocList<T extends DocForDrill>({ docs, meta, onOpenSku }: {
  docs: T[]; meta: (d: T) => string; onOpenSku?: (guid: string) => void
}) {
  const [open, setOpen] = useState<number | null>(docs.length === 1 ? 0 : null)
  return (
    <div>
      {docs.map((d, i) => (
        <div key={i} className="border-t border-border/30 first:border-t-0">
          <button onClick={() => setOpen(open === i ? null : i)}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent/20 text-left">
            <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${open === i ? 'rotate-90' : ''}`} />
            <span className="tabular-nums text-muted-foreground shrink-0">{d.number ?? '—'}</span>
            <span className="flex-1 truncate">{meta(d)}</span>
          </button>
          {open === i && <div className="bg-background/40"><DocLines lines={d.lines} onOpenSku={onOpenSku} /></div>}
        </div>
      ))}
    </div>
  )
}

export function DocsModal<T extends DocForDrill>({ title, subtitle, docs, meta, onOpenSku, onClose }: {
  title: string; subtitle?: string; docs: T[]
  meta?: (d: T) => string; onOpenSku?: (guid: string) => void; onClose: () => void
}) {
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="text-base">{title}</DialogTitle>
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
        </DialogHeader>
        <div className="max-h-[65vh] overflow-auto rounded-md border border-border/40">
          {docs.length
            ? <DocList docs={docs} meta={meta ?? ((d) => d.meta ?? '')} onOpenSku={onOpenSku} />
            : <div className="px-3 py-6 text-sm text-muted-foreground text-center">Документов за период нет</div>}
        </div>
      </DialogContent>
    </Dialog>
  )
}
