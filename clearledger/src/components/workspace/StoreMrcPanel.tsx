/**
 * «МРЦ табака» (О-3, слой политик) — регуляторный контроль максимальной
 * розничной цены. Продажа выше МРЦ = нарушение (ФЗ-15). Справочник МРЦ грузится
 * CSV (штрихкод/артикул/имя → SKU через регистр ЦБ), сравнивается с ценой в
 * рознице (StockOnHand.ЦенаВРознице). Далее — фид «Честный знак».
 * Данные: /api/store/mrc, /api/store/mrc/import (GoodsDashboardService).
 */
import { useMemo, useRef, useState } from 'react'
import { rowDrill } from './rowDrill'
import { SkuDetailModal } from './SkuDetailModal'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { ShieldAlert, ShieldCheck, Upload, Loader2, FileWarning } from 'lucide-react'
import { getStoreMrc, importStoreMrc, type MrcItem, type MrcImportRow, type MrcImportResult } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/** Разбор CSV МРЦ: авто-определение разделителя (,/;) и колонок; fallback —
 * безголовый «штрихкод,мрц». */
function parseCsv(text: string): MrcImportRow[] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim())
  if (!lines.length) return []
  const semis = (lines[0].match(/;/g) || []).length
  const commas = (lines[0].match(/,/g) || []).length
  const tabs = (lines[0].match(/\t/g) || []).length
  const delim = tabs >= semis && tabs >= commas ? '\t' : semis >= commas ? ';' : ','
  const split = (l: string) => l.split(delim).map((c) => c.trim().replace(/^"|"$/g, ''))
  const header = split(lines[0]).map((h) => h.toLowerCase())
  const col = (keys: string[]) => header.findIndex((h) => keys.some((k) => h.includes(k)))
  let iBc = col(['штрихкод', 'штрих', 'barcode', 'gtin', 'ean'])
  let iArt = col(['артикул', 'article'])
  let iName = col(['наимен', 'назван', 'товар', 'name'])
  let iMrc = col(['мрц', 'mrc', 'макс.роз', 'макс роз', 'предельн'])
  let start = 1
  if (iMrc < 0) { start = 0; iBc = 0; iMrc = 1; iArt = -1; iName = -1 } // безголовый: штрихкод,мрц
  const rows: MrcImportRow[] = []
  for (let i = start; i < lines.length; i++) {
    const c = split(lines[i])
    const mrc = iMrc >= 0 ? c[iMrc] : ''
    if (mrc == null || mrc === '') continue
    rows.push({
      barcode: iBc >= 0 ? c[iBc] : undefined,
      article: iArt >= 0 ? c[iArt] : undefined,
      name: iName >= 0 ? c[iName] : undefined,
      mrc,
    })
  }
  return rows
}

export function StoreMrcPanel({ companyId, dateFrom, dateTo }: { companyId: string; dateFrom: string; dateTo: string }) {
  // Строка = товар: раскрывается его карточка (та же, что в «Ассортименте»).
  const [openSku, setOpenSku] = useState<string | null>(null)
  void dateFrom; void dateTo // контроль МРЦ — на текущей рознице, период не нужен
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [onlyViol, setOnlyViol] = useState(false)
  const [q, setQ] = useState('')
  const [importMsg, setImportMsg] = useState<MrcImportResult | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-mrc', companyId],
    queryFn: () => getStoreMrc(),
  })

  const imp = useMutation({
    mutationFn: (rows: MrcImportRow[]) => importStoreMrc(rows),
    onSuccess: (res) => {
      setImportMsg(res)
      qc.invalidateQueries({ queryKey: ['store-mrc', companyId] })
    },
  })

  const onFile = async (f: File | null) => {
    if (!f) return
    setImportMsg(null)
    const text = await f.text()
    const rows = parseCsv(text)
    if (!rows.length) { setImportMsg({ imported: 0, unresolved_count: 0, unresolved: [] }); return }
    imp.mutate(rows)
    if (fileRef.current) fileRef.current.value = ''
  }

  const items = useMemo(() => {
    const ql = q.toLowerCase().trim()
    return (data?.items ?? [])
      .filter((i) => !onlyViol || i.over)
      .filter((i) => !ql || i.name.toLowerCase().includes(ql) || (i.barcode ?? '').includes(q))
  }, [data, onlyViol, q])
  const показ = useVisible(items)

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка контроля МРЦ…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки. <button type="button" className="underline" onClick={() => refetch()}>Повторить</button></div>
  if (!data) return null

  const s = data.summary
  const KPIS = [
    { label: 'Под контролем', value: nf(s.controlled), hint: 'SKU с заданной МРЦ' },
    { label: 'Нарушений', value: nf(s.violations), cls: s.violations > 0 ? 'text-red-400/90' : 'text-emerald-300/80', hint: 'цена выше МРЦ' },
    { label: 'Без цены розницы', value: nf(s.missing_price), hint: 'нет в остатках' },
    { label: 'Табак без МРЦ', value: nf(s.missing_mrc), cls: s.missing_mrc > 0 ? 'text-amber-300/90' : '', hint: 'дозагрузить справочник' },
  ]

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold flex items-center gap-2">
            {s.violations > 0 ? <ShieldAlert className="h-4 w-4 text-red-400/90" /> : <ShieldCheck className="h-4 w-4 text-emerald-300/80" />}
            МРЦ табака
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Продажа выше максимальной розничной цены — нарушение. Розница ЦБ vs справочник МРЦ.
            Загрузите CSV (штрихкод / артикул / имя → МРЦ).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".csv,text/csv,text/plain" className="hidden"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
          <button type="button" onClick={() => fileRef.current?.click()} disabled={imp.isPending}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-xs bg-primary/15 text-primary hover:bg-primary/25 disabled:opacity-50">
            {imp.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            Импорт CSV
          </button>
        </div>
      </div>

      {importMsg && (
        <div className={`rounded-md border px-3 py-2 text-xs flex items-center gap-2 ${importMsg.imported > 0 ? 'border-emerald-400/40 text-emerald-300/90' : 'border-amber-400/40 text-amber-300/90'}`}>
          <FileWarning className="h-4 w-4 shrink-0" />
          {importMsg.imported > 0
            ? <>Загружено МРЦ: <b>{importMsg.imported}</b>. Не сопоставлено строк: {importMsg.unresolved_count}.</>
            : <>Ничего не загружено. Проверьте формат: колонки «штрихкод»/«артикул»/«наименование» + «МРЦ» (или безголовый «штрихкод,мрц»). Не сопоставлено: {importMsg.unresolved_count}.</>}
        </div>
      )}

      <div className="grid gap-2.5 grid-cols-2 lg:grid-cols-4">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.cls ?? ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5">{k.hint}</div>}
          </div>
        ))}
      </div>

      {s.controlled === 0 ? (
        <div className="rounded-lg border border-dashed border-border/50 p-6 text-sm text-muted-foreground">
          Справочник МРЦ пуст. Загрузите CSV с максимальными розничными ценами табака —
          система сопоставит по штрихкоду (GTIN) и покажет нарушения (продажа выше МРЦ).
          <br /><span className="text-[11px]">Формат: <code>штрихкод;МРЦ</code> или колонки «Штрихкод», «Наименование», «МРЦ».</span>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => setOnlyViol((v) => !v)}
                className={`h-7 px-2.5 rounded-md text-xs border ${onlyViol ? 'border-red-400/50 text-red-400/90 bg-red-400/10' : 'border-border/50 text-muted-foreground hover:bg-accent/40'}`}>
                Только нарушения{s.violations > 0 ? ` (${s.violations})` : ''}
              </button>
              <span className="text-xs text-muted-foreground">Найдено {nf(items.length)}</span>
            </div>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="поиск товара / ШК…"
              className="text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background w-56" />
          </div>

          <div className="overflow-x-auto rounded-lg border border-border/50">
            <table className="w-full text-xs">
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium text-left">Товар</th>
                  <th className="px-3 py-2 font-medium text-left">Штрихкод</th>
                  <th className="px-3 py-2 font-medium text-right">МРЦ</th>
                  <th className="px-3 py-2 font-medium text-right">Цена розницы</th>
                  <th className="px-3 py-2 font-medium text-right">Δ к МРЦ</th>
                  <th className="px-3 py-2 font-medium text-center">Статус</th>
                </tr>
              </thead>
              <tbody>
                {показ.visible.map((i: MrcItem) => (
                  <tr key={i.ref}
                      {...rowDrill(() => setOpenSku(i.ref), `${i.name} — карточка товара`,
                        `border-t border-border/30 ${i.over ? 'bg-red-400/[0.06]' : ''}`)}>
                    <td className="px-3 py-1.5">{i.name}</td>
                    <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{i.barcode ?? '—'}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{fmtMoney(i.mrc)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{i.retail_price != null ? fmtMoney(i.retail_price) : '—'}</td>
                    <td className={`px-3 py-1.5 text-right tabular-nums ${i.diff != null && i.diff > 0 ? 'text-red-400/90' : 'text-muted-foreground'}`}>
                      {i.diff != null ? `${i.diff > 0 ? '+' : ''}${fmtMoney(i.diff)}` : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-center">
                      {i.retail_price == null
                        ? <span className="text-muted-foreground/60">нет цены</span>
                        : i.over
                          ? <span className="inline-flex items-center gap-1 text-red-400/90"><ShieldAlert className="h-3 w-3" /> нарушение</span>
                          : <span className="inline-flex items-center gap-1 text-emerald-300/80"><ShieldCheck className="h-3 w-3" /> ок</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ShowMore {...показ} onMore={показ.more} onAll={показ.all} unit="позиций" />
            {items.length === 0 && <div className="px-3 py-6 text-sm text-muted-foreground text-center">Нет строк под фильтром.</div>}
          </div>
        </>
      )}
      {openSku && (
        <SkuDetailModal guid={openSku} dateFrom={dateFrom} dateTo={dateTo}
          onClose={() => setOpenSku(null)} />
      )}
    </div>
  )
}
