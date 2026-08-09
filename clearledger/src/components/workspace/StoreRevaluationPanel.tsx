/**
 * «Переоценка» раздела «Магазин» — реестр ПереоценкаТоваровАЗК ЦБ ЭЛСИ.АЗК:
 * изменения розничных цен (старая→новая, Δ%), подорожания/удешевления, влияние
 * на стоимость остатка (Σ Δ×кол). Данные: /api/store/revaluation. Клик по док → строки.
 * ⚠ Экстремальные % часто = коррекции плейсхолдер-цен / весовые (цена за баз. ед.).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStoreRevaluation, type StoreRevalDoc, type StoreRevalMove } from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'
import { ShowMore, useVisible } from '@/components/common/ShowMore'
import { rowDrill } from './rowDrill'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const pct = (v: number | null) => (v == null ? '—' : `${v > 0 ? '+' : ''}${nf(v, 1)}%`)

function MoveList({ title, moves, up }: { title: string; moves: StoreRevalMove[]; up: boolean }) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 p-3">
      <div className="text-sm font-medium mb-2">{title}</div>
      <div className="space-y-1.5">
        {moves.length === 0 && <div className="text-xs text-muted-foreground">Нет данных</div>}
        {moves.map((m) => (
          <div key={m.ref ?? m.name} className="flex items-center justify-between gap-2 text-xs">
            <span className="truncate" title={m.name}>{m.name}</span>
            {/* Цена с единицей: у весового товара база — грамм, и «0,35» без единицы
                читается как цена за килограмм (в имени карточки стоит «1 кг.»). */}
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {nf(m.old, 2)}→{nf(m.new, 2)}{m.unit ? ` ₽/${m.unit}` : ''}
            </span>
            {/* Сумма — главная величина: во столько обошлась переоценка на остатке той
                даты. Процент рядом отвечает на «насколько», но сам по себе обманывает:
                25 копеек за грамм дают +250%. */}
            <span className={`shrink-0 tabular-nums w-24 text-right ${up ? 'text-emerald-300/80' : 'text-red-400/80'}`}>
              {m.amount == null ? '—' : fmtMoney(m.amount)}
            </span>
            <span className="shrink-0 tabular-nums w-16 text-right text-muted-foreground">{pct(m.pct)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function StoreRevaluationPanel({ companyId, dateFrom, dateTo, stations }: {
  companyId: string; dateFrom?: string; dateTo?: string; stations?: string[]
}) {
  const [reason, setReason] = useState<string | null>(null)
  const [openDoc, setOpenDoc] = useState<StoreRevalDoc | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['store-revaluation', companyId, dateFrom, dateTo, stations?.join(',') || '', reason],
    queryFn: () => getStoreRevaluation({ dateFrom, dateTo, stations, reason: reason || undefined }),
  })

  const docs = data?.docs ?? []
  const visible = useVisible(docs)

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка переоценок…</div>
  if (error) return (
    <div className="p-6 text-sm text-red-400/90">
      Не удалось загрузить переоценки.{' '}
      <button type="button" className="underline" onClick={() => refetch()}>Повторить</button>
    </div>
  )
  if (!data) return null

  const s = data.summary
  const maxCount = Math.max(1, ...data.by_reason.map((r) => r.count))

  const KPIS: { label: string; value: string; hint?: string; cls?: string }[] = [
    { label: 'Переоценок', value: nf(s.docs_count), hint: `${s.period_from ?? ''} – ${s.period_to ?? ''}` },
    { label: 'Строк подорожало / подешевело', value: `${nf(s.up_lines)} / ${nf(s.down_lines)}`, hint: 'строк в документах, не документов' },
    { label: 'Средн. изменение', value: s.avg_pct == null ? '—' : `${s.avg_pct > 0 ? '+' : ''}${nf(s.avg_pct, 1)}%`, cls: (s.avg_pct ?? 0) < 0 ? 'text-red-400/90' : 'text-emerald-300/90' },
    { label: 'Влияние на стоимость', value: s.value_impact === 0 ? '—' : fmtMoney(s.value_impact), hint: 'Σ Δцены × остаток', cls: s.value_impact < 0 ? 'text-red-400/90' : 'text-emerald-300/90' },
  ]

  return (
    <div className="p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold">Переоценка</h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          Реестр переоценок из ЦБ: старая→новая цена, Δ%, влияние на стоимость остатка. Клик по документу — строки.
          {reason && <> Фильтр: <b>{reason}</b> <button type="button" className="underline ml-1" onClick={() => setReason(null)}>сбросить</button></>}
        </p>
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

      <div className="grid gap-4 lg:grid-cols-2">
        <MoveList title="Подорожание — дороже всего обошлось" moves={data.top_up} up />
        <MoveList title="Удешевление — дороже всего обошлось" moves={data.top_down} up={false} />
      </div>

      {/* Направления (клик = фильтр) */}
      <div className="rounded-lg border border-border/50 bg-card/40 p-3">
        <div className="text-sm font-medium mb-2">Переоценки по направлению</div>
        <div className="space-y-1.5">
          {data.by_reason.map((r) => (
            <button
              type="button" key={r.reason} onClick={() => setReason(reason === r.reason ? null : r.reason)}
              aria-pressed={reason === r.reason}
              className={`w-full flex items-center gap-2 text-xs group ${reason === r.reason ? 'font-semibold' : ''}`}
            >
              <span className="w-40 text-left truncate shrink-0">{r.reason}</span>
              <span className="flex-1 h-3 bg-muted/30 rounded overflow-hidden">
                <span className="block h-full bg-amber-400/40 group-hover:bg-amber-400/60 transition-colors" style={{ width: `${(r.count / maxCount) * 100}%` }} />
              </span>
              <span className="w-12 text-right tabular-nums text-muted-foreground shrink-0">{r.count}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Реестр */}
      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium text-left whitespace-nowrap">Дата</th>
              <th className="px-3 py-2 font-medium text-left">Номер</th>
              <th className="px-3 py-2 font-medium text-left">Направление</th>
              <th className="px-3 py-2 font-medium text-right">Позиций</th>
              <th className="px-3 py-2 font-medium text-right whitespace-nowrap">Влияние ₽</th>
            </tr>
          </thead>
          <tbody>
            {visible.visible.map((d) => (
              <tr key={d.ref}
                {...rowDrill(d.positions ? () => setOpenDoc(d) : null, `Открыть переоценку ${d.number ?? ''}`,
                  `border-t border-border/30 ${d.positions ? 'hover:bg-accent/20' : 'opacity-60'}`)}>
                <td className="px-3 py-1.5 whitespace-nowrap">{d.date ?? '—'}</td>
                <td className="px-3 py-1.5 tabular-nums">{d.number ?? '—'}</td>
                <td className="px-3 py-1.5">{d.reason}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{d.positions}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${d.value_impact < 0 ? 'text-red-400/70' : d.value_impact > 0 ? 'text-emerald-300/70' : ''}`}>{d.value_impact === 0 ? '—' : fmtMoney(d.value_impact)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ShowMore shown={visible.visible.length} total={docs.length} hasMore={visible.hasMore}
          onMore={visible.more} onAll={visible.all} unit="документов" />
        {docs.length === 0 && (
          <div className="px-3 py-6 text-sm text-muted-foreground text-center">
            За выбранный период и станции переоценок нет.
          </div>
        )}
      </div>

      {/* Модалка строк документа */}
      {openDoc && (
        <div className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/50 p-4" onClick={() => setOpenDoc(null)}>
          <div className="bg-card border border-border rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
              <div>
                <div className="text-sm font-semibold">Переоценка {openDoc.number} · {openDoc.date}</div>
                <div className="text-xs text-muted-foreground">
                  {openDoc.warehouse_name} · {openDoc.reason} · {openDoc.positions} позиций
                  {openDoc.comment && <> · {openDoc.comment}</>}
                </div>
              </div>
              <button type="button" aria-label="Закрыть" onClick={() => setOpenDoc(null)} className="text-muted-foreground hover:text-foreground text-lg leading-none px-2">×</button>
            </div>
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead className="bg-muted/30 text-muted-foreground sticky top-0">
                  <tr>
                    <th className="px-3 py-2 font-medium text-left">Товар</th>
                    <th className="px-3 py-2 font-medium text-right">Старая</th>
                    <th className="px-3 py-2 font-medium text-right">Новая</th>
                    <th className="px-3 py-2 font-medium text-right">Δ</th>
                    <th className="px-3 py-2 font-medium text-right">Δ%</th>
                  </tr>
                </thead>
                <tbody>
                  {openDoc.lines.map((ln, idx) => (
                    <tr key={`${ln.ref}-${idx}`} className="border-t border-border/30">
                      <td className="px-3 py-1.5">{ln.name}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{nf(ln.old, 2)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{nf(ln.new, 2)}</td>
                      <td className={`px-3 py-1.5 text-right tabular-nums ${ln.delta < 0 ? 'text-red-400/80' : 'text-emerald-300/80'}`}>{ln.delta > 0 ? '+' : ''}{nf(ln.delta, 2)}</td>
                      <td className={`px-3 py-1.5 text-right tabular-nums ${(ln.pct ?? 0) < 0 ? 'text-red-400/80' : 'text-emerald-300/80'}`}>{pct(ln.pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
