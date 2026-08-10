/**
 * «Списания» раздела «Магазин» — реестр СписаниеТоваров ЦБ ЭЛСИ.АЗК + причины
 * (недостача из инвентаризации / брак / срок / приказ / …) и топ списанных SKU.
 * Данные: /api/store/writeoffs (GoodsDashboardService.writeoffs). Клик по док → строки.
 * Фильтр по причине — client-side (клик по строке разбивки).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { StationDocsBlock } from './StationDocsBlock'
import { getStoreWriteoffs, type StoreWriteoffDoc } from '@/services/storeService'
import { SnapshotBadge } from '@/components/common/SnapshotBadge'
import { ModalCard } from '@/components/ui/modal-card'
import { fmtMoney } from '@/services/analyticsService'
import { rowDrill } from './rowDrill'
import { NomenclatureCardModal } from './NomenclatureCardModal'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const money = (n: number) => (n === 0 ? '—' : fmtMoney(n))

export function StoreWriteoffPanel({ companyId, dateFrom, dateTo, stations }: {
  companyId: string; dateFrom?: string; dateTo?: string; stations?: string[]
}) {
  const [warehouse, setWarehouse] = useState<string | undefined>(undefined)
  const [reason, setReason] = useState<string | null>(null)
  const [openDoc, setOpenDoc] = useState<StoreWriteoffDoc | null>(null)
  const [sku, setSku] = useState<string | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-writeoffs', companyId, warehouse ?? '', dateFrom, dateTo, stations?.join(',') ?? ''],
    queryFn: () => getStoreWriteoffs({ warehouse, dateFrom, dateTo, stations }),
  })

  const docs = useMemo(
    () => (data?.docs ?? []).filter((d) => !reason || d.reason === reason),
    [data, reason],
  )
  const показ = useVisible(docs)

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка списаний…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Ошибка загрузки списаний. <button type="button" className="underline" onClick={() => refetch()}>Повторить</button></div>
  if (!data) return null

  const tot = docs.reduce((s, d) => s + d.total_amount, 0)
  const invAmt = docs.filter((d) => d.from_inventory).reduce((s, d) => s + d.total_amount, 0)
  const maxReason = Math.max(1, ...data.by_reason.map((r) => Math.abs(r.amount)))

  const KPIS: { label: string; value: string; hint?: string; cls?: string }[] = [
    { label: 'Списаний', value: nf(docs.length), hint: `${data.summary.period_from ?? ''} – ${data.summary.period_to ?? ''}` },
    { label: 'Сумма списаний', value: money(tot), cls: 'text-red-400/90' },
    { label: 'Из недостач (инв.)', value: money(invAmt), hint: '= недостачи с экрана Инвентаризация (не суммировать)' },
    { label: 'Прочие причины', value: money(tot - invAmt), hint: 'брак/срок/приказ' },
  ]

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-semibold inline-flex items-center gap-2">Списания <SnapshotBadge at={data.snapshot_at} /></h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Реестр списаний из ЦБ + разбор причин (недостача из инвентаризации, брак, срок годности…).
            Клик по документу — строки. {reason && <>Фильтр: <b>{reason}</b> <button className="underline ml-1" onClick={() => setReason(null)}>сбросить</button></>}
          </p>
        </div>
        <select
          value={warehouse ?? ''} onChange={(e) => setWarehouse(e.target.value || undefined)}
          className="text-xs px-2 py-1.5 rounded-md border border-border/50 bg-background"
        >
          <option value="">Все склады магазина</option>
          {data.warehouses.map((w) => (
            <option key={w.code} value={w.code}>{w.name ?? w.code} ({w.count})</option>
          ))}
        </select>
      </div>

      <div className="grid gap-2.5 grid-cols-2 lg:grid-cols-4">
        {KPIS.map((k) => (
          <div key={k.label} className="rounded-lg border border-border/50 bg-card/40 p-3">
            <div className="text-[11px] text-muted-foreground">{k.label}</div>
            <div className={`text-lg font-semibold tabular-nums mt-0.5 ${k.cls ?? ''}`}>{k.value}</div>
            {k.hint && <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{k.hint}</div>}
          </div>
        ))}
      </div>

      {/* Разбивка по причинам (клик = фильтр) */}
      <div className="rounded-lg border border-border/50 bg-card/40 p-3">
        <div className="text-sm font-medium mb-2">Причины списаний</div>
        <div className="space-y-1.5">
          {data.by_reason.map((r) => (
            <button
              key={r.reason} onClick={() => setReason(reason === r.reason ? null : r.reason)}
              className={`w-full flex items-center gap-2 text-xs group ${reason === r.reason ? 'font-semibold' : ''}`}
            >
              <span className="w-44 text-left truncate shrink-0">{r.reason}</span>
              <span className="flex-1 h-3 bg-muted/30 rounded overflow-hidden">
                <span className="block h-full bg-red-400/40 group-hover:bg-red-400/60 transition-colors" style={{ width: `${(Math.abs(r.amount) / maxReason) * 100}%` }} />
              </span>
              <span className="w-28 text-right tabular-nums shrink-0">{fmtMoney(r.amount)}</span>
              <span className="w-10 text-right tabular-nums text-muted-foreground shrink-0">{r.count}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        {/* Реестр */}
        <div className="overflow-x-auto rounded-lg border border-border/50 h-fit">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Дата</th>
                <th className="px-3 py-2 font-medium text-left">Номер</th>
                <th className="px-3 py-2 font-medium text-left">Смена</th>
                <th className="px-3 py-2 font-medium text-left">Причина</th>
                <th className="px-3 py-2 font-medium text-right">Позиций</th>
                <th className="px-3 py-2 font-medium text-right">Сумма</th>
              </tr>
            </thead>
            <tbody>
              {показ.visible.map((d) => (
                <tr key={d.ref} {...rowDrill(
                  d.lines.length ? () => setOpenDoc(d) : null,
                  `списание ${d.number ?? ''}`,
                  'border-t border-border/30',
                )}>
                  <td className="px-3 py-1.5 whitespace-nowrap">{d.date ?? '—'}</td>
                  <td className="px-3 py-1.5 tabular-nums">{d.number ?? '—'}</td>
                  <td className="px-3 py-1.5 tabular-nums text-muted-foreground" title={d.shift_reason ?? undefined}>{d.shift_number ?? '—'}</td>
                  <td className="px-3 py-1.5">
                    {d.reason}
                    {d.comment && <span className="text-muted-foreground/60 ml-1" title={d.comment}>· {d.comment.slice(0, 24)}</span>}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{d.positions || '—'}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-red-400/80">{money(d.total_amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {docs.length > 300 && <ShowMore {...показ} onMore={показ.more} onAll={показ.all} unit="документов" />}
          {docs.length === 0 && (
            <div className="px-3 py-6 text-sm text-muted-foreground text-center">
              За выбранный период списаний нет.
            </div>
          )}
        </div>

        {/* Топ списанных товаров */}
        <div className="rounded-lg border border-border/50 bg-card/40 p-3 h-fit">
          <div className="text-sm font-medium mb-2">Топ списанных товаров</div>
          <div className="space-y-1.5">
            {data.top_sku.length === 0 && <div className="text-xs text-muted-foreground">Нет данных</div>}
            {data.top_sku.map((t) => (
              <div key={t.name}
                {...rowDrill(t.ref ? () => setSku(t.ref!) : null, `карточка товара ${t.name}`,
                  'flex items-center justify-between gap-2 text-xs rounded px-1 -mx-1')}>
                <span className="truncate" title={t.name}>{t.name}</span>
                <span className="tabular-nums text-red-400/80 shrink-0">{fmtMoney(t.amount)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Модалка строк документа */}
      {openDoc && (
        <ModalCard
          className="max-w-2xl max-h-[80vh]"
          bodyClassName=""
          onClose={() => setOpenDoc(null)}
          title={<span className="text-sm">Списание {openDoc.number} · {openDoc.date}</span>}
          subtitle={
            <>
              {openDoc.warehouse_name} · {openDoc.reason} · {openDoc.positions} позиций ·
              <span className="text-red-400/80"> {fmtMoney(openDoc.total_amount)}</span>
              {openDoc.comment && <> · {openDoc.comment}</>}
            </>
          }
        >
              <table className="w-full text-xs">
                <thead className="bg-muted/30 text-muted-foreground sticky top-0">
                  <tr>
                    <th className="px-3 py-2 font-medium text-left">Товар</th>
                    <th className="px-3 py-2 font-medium text-right">Кол-во</th>
                    <th className="px-3 py-2 font-medium text-right">Цена</th>
                    <th className="px-3 py-2 font-medium text-right">Сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {openDoc.lines.map((ln, idx) => (
                    <tr key={`${ln.ref}-${idx}`} className="border-t border-border/30">
                      <td className="px-3 py-1.5">{ln.name}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{nf(ln.qty, 3)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{fmtMoney(ln.price)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-red-400/80">{fmtMoney(ln.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
        </ModalCard>
      )}

      {sku && <NomenclatureCardModal guid={sku} companyId={companyId} dateFrom={dateFrom ?? ''} dateTo={dateTo ?? ''} stations={stations} onClose={() => setSku(null)} />}

      {/* Второй источник того же предмета: реестр выше — история 1С, здесь —
          то, что заводят на самой АЗС. Пока 1С ведёт станцию, они идут рядом. */}
      <StationDocsBlock kind="writeoff" dateFrom={dateFrom} dateTo={dateTo} title="Списания станции" />
    </div>
  )
}
