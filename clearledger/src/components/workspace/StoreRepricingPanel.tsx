/**
 * «Переоценка» — рабочее место ценообразования сети.
 *
 * Менеджер приходит с решением («поднять напитки на 5 %», «вывести кухню к
 * наценке 300 %»), а не с карточкой: карточками правят исключения. Поэтому
 * порядок экрана — порядок решения: кого меняем → по какому правилу → что из
 * этого выйдет → применить.
 *
 * Между предпросмотром и кассой стоит явное подтверждение, и это не лишний шаг:
 * массовое правило — самая опасная операция раздела, одна опечатка в поле
 * «процент» переписывает прайс всей сети. Ограничители (пол маржи, потолок шага,
 * защита ключевых позиций) включены по умолчанию — они из практики сетевого
 * ритейла, а не из осторожности ради осторожности.
 *
 * Правила считаются теми же формулами, что и на станции
 * (agent/internal/store/repricing.go): если центр считает наценку иначе, спор о
 * цене превращается в спор о методике.
 *
 * Данные: /api/store/repricing/preview · /api/store/repricing/apply.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Kpi } from './analytics/Kpi'
import { rowDrill } from './rowDrill'
import {
  previewRepricing, applyRepricing,
  type RepricingRule, type RepricingPreview,
} from '@/services/storeService'
import { fmtMoney } from '@/services/analyticsService'

const nf = (n: number, d = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)
const знак = (n: number) => (n > 0 ? '+' : '')

const СПОСОБЫ = [
  { key: 'процент', label: '± % к цене', hint: 'поднять или опустить нынешнюю цену на процент' },
  { key: 'рубли', label: '± ₽ к цене', hint: 'сдвинуть цену на фиксированную сумму' },
  { key: 'наценка', label: 'наценка от себестоимости', hint: 'цена = себестоимость + процент наценки' },
  { key: 'маржа', label: 'доля маржи в цене', hint: 'сколько процентов цены остаётся сети' },
  { key: 'цена', label: 'одна цена на всех', hint: 'поставить всем отобранным одинаковую цену' },
]
const ОКРУГЛЕНИЯ = [
  { key: '', label: 'как посчиталось' },
  { key: '0.1', label: 'до 10 копеек' },
  { key: '1', label: 'до рубля' },
  { key: '5', label: 'до 5 рублей' },
  { key: '0.9', label: 'хвост ,90' },
  { key: '0.99', label: 'хвост ,99' },
]

function Поле({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs" title={hint}>
      <span className="text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}

const вход = 'h-8 rounded-md border border-border/60 bg-background px-2 text-sm'

export function StoreRepricingPanel({ dateFrom, dateTo, stations }: {
  companyId: string; dateFrom: string; dateTo: string; stations?: string[]
}) {
  const [rule, setRule] = useState<RepricingRule>({
    mode: 'процент', value: 0, round: '1', floor: 5, step: 15, kvi: false,
    group: '', q: '', sold: true,
  })
  const [выбраны, setВыбраны] = useState<Set<string>>(new Set())
  const [итог, setИтог] = useState<string | null>(null)

  const коды = stations?.map(Number).filter((n) => !Number.isNaN(n))
  const тело = (): RepricingRule => ({
    ...rule, date_from: dateFrom, date_to: dateTo,
    stations: коды?.length ? коды : undefined,
  })

  const счёт = useMutation<RepricingPreview>({
    mutationFn: () => previewRepricing(тело()),
    onSuccess: () => { setВыбраны(new Set()); setИтог(null) },
  })
  const применение = useMutation({
    mutationFn: () => applyRepricing({ ...тело(), items: выбраны.size ? [...выбраны] : undefined }),
    onSuccess: (r) => {
      setИтог(`${r.note}. Позиций: ${r.applied}, станций: ${r.stations}.`)
      счёт.mutate()
    },
  })

  const p = счёт.data
  const поедут = p?.rows.filter((r) => !r.reject) ?? []
  const отмечено = выбраны.size || поедут.length

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Переоценка</h2>
        <p className="text-sm text-muted-foreground max-w-4xl mt-1">
          Отберите позиции, задайте правило, посмотрите, что из этого выйдет, и только потом
          применяйте. Центр распоряжается <b>центральными</b> ценами; там, где право отдано
          станции, правило не трогает ничего — иначе решение АЗС молча затиралось бы сетевым.
        </p>
      </div>

      <section className="rounded-lg border border-border/50 p-4 space-y-4">
        <div>
          <div className="text-xs text-muted-foreground mb-2">Кого меняем</div>
          <div className="flex flex-wrap gap-3 items-end">
            <Поле label="Группа">
              <input className={вход} value={rule.group} placeholder="например, Табак"
                     onChange={(e) => setRule({ ...rule, group: e.target.value })} />
            </Поле>
            <Поле label="Название содержит">
              <input className={вход} value={rule.q} placeholder="часть названия"
                     onChange={(e) => setRule({ ...rule, q: e.target.value })} />
            </Поле>
            <label className="flex items-center gap-2 text-xs h-8">
              <input type="checkbox" checked={!!rule.sold}
                     onChange={(e) => setRule({ ...rule, sold: e.target.checked })} />
              только то, что продаётся
            </label>
          </div>
        </div>

        <div>
          <div className="text-xs text-muted-foreground mb-2">Как меняем</div>
          <div className="flex flex-wrap gap-3 items-end">
            <Поле label="Способ" hint={СПОСОБЫ.find((с) => с.key === rule.mode)?.hint}>
              <select className={вход} value={rule.mode}
                      onChange={(e) => setRule({ ...rule, mode: e.target.value })}>
                {СПОСОБЫ.map((с) => <option key={с.key} value={с.key}>{с.label}</option>)}
              </select>
            </Поле>
            <Поле label="Значение">
              <input className={`${вход} w-24`} inputMode="decimal" value={rule.value}
                     onChange={(e) => setRule({ ...rule, value: Number(e.target.value.replace(',', '.')) || 0 })} />
            </Поле>
            <Поле label="Округление">
              <select className={вход} value={rule.round}
                      onChange={(e) => setRule({ ...rule, round: e.target.value })}>
                {ОКРУГЛЕНИЯ.map((о) => <option key={о.key} value={о.key}>{о.label}</option>)}
              </select>
            </Поле>
            <Поле label="Пол маржи, %" hint="ниже этой доли маржи позиция не поедет">
              <input className={`${вход} w-20`} inputMode="decimal" value={rule.floor}
                     onChange={(e) => setRule({ ...rule, floor: Number(e.target.value.replace(',', '.')) || 0 })} />
            </Поле>
            <Поле label="Потолок шага, %" hint="разовое изменение больше этого не применяется">
              <input className={`${вход} w-20`} inputMode="decimal" value={rule.step}
                     onChange={(e) => setRule({ ...rule, step: Number(e.target.value.replace(',', '.')) || 0 })} />
            </Поле>
            <label className="flex items-center gap-2 text-xs h-8"
                   title="позиции, дающие 80 % выручки: по ним покупатель судит об уровне цен">
              <input type="checkbox" checked={rule.kvi}
                     onChange={(e) => setRule({ ...rule, kvi: e.target.checked })} />
              трогать ключевые позиции
            </label>
            <button className="h-8 px-4 rounded-md bg-primary text-primary-foreground text-sm"
                    onClick={() => счёт.mutate()} disabled={счёт.isPending}>
              {счёт.isPending ? 'Считаем…' : 'Посчитать'}
            </button>
          </div>
        </div>
      </section>

      {итог && (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm">{итог}</div>
      )}

      {p && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label="Изменится" value={nf(p.total.changed)}
                 sub={`из ${nf(p.total.selected)} отобранных позиций`} />
            <Kpi label="Средний рост цены" value={`${знак(p.total.avg_growth)}${nf(p.total.avg_growth, 2)} %`}
                 sub="взвешенно по выручке — крупные позиции весят больше" />
            <Kpi label="Эффект на маржу" value={fmtMoney(p.total.effect)}
                 sub="оценка при том же объёме продаж" />
            <Kpi label="Не поедет" value={nf(p.total.rejected)}
                 sub="каждая причина расписана ниже" />
          </div>

          {!!p.reasons.length && (
            <section className="rounded-lg border border-border/50 p-4">
              <h3 className="text-sm font-semibold">Почему часть позиций не изменится</h3>
              <p className="text-xs text-muted-foreground mt-1">
                Молчаливый пропуск — худший исход переоценки: цена на полке одна, в голове другая.
              </p>
              <table className="w-full text-xs mt-3">
                <tbody>
                  {p.reasons.map((r) => (
                    <tr key={r.reason} className="border-b border-border/30">
                      <td className="py-1.5 pr-3 w-64">{r.reason}</td>
                      <td className="py-1.5 pr-3 text-right w-20">{nf(r.count)}</td>
                      <td className="py-1.5 text-muted-foreground">{r.what}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {p.by_station.length > 1 && (
            <section className="rounded-lg border border-border/50 p-4">
              <h3 className="text-sm font-semibold">По станциям</h3>
              <table className="w-full text-xs mt-3">
                <tbody>
                  {p.by_station.map((с) => (
                    <tr key={с.station_id} className="border-b border-border/30">
                      <td className="py-1.5 pr-3">АЗС {с.station_id}</td>
                      <td className="py-1.5 pr-3 text-right">{nf(с.changed)} изменится</td>
                      <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(с.rejected)} нет</td>
                      <td className="py-1.5 text-right font-medium">{fmtMoney(с.effect)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section className="rounded-lg border border-border/50 p-4">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <h3 className="text-sm font-semibold">Что станет с ценами</h3>
                <p className="text-xs text-muted-foreground mt-1">
                  Сверху — позиции, которые двигают больше всего денег. Показано {nf(p.shown)} из {nf(p.total_rows)}.
                  {выбраны.size > 0 && ` Отмечено вручную: ${выбраны.size}.`}
                </p>
              </div>
              <button
                className="h-8 px-4 rounded-md bg-primary text-primary-foreground text-sm disabled:opacity-50"
                disabled={применение.isPending || !поедут.length}
                onClick={() => {
                  if (confirm(`Применить новые цены к ${отмечено} позициям? Цены уедут на станции заданиями.`)) {
                    применение.mutate()
                  }
                }}>
                {применение.isPending ? 'Применяем…' : `Применить (${отмечено})`}
              </button>
            </div>

            <div className="overflow-x-auto mt-3">
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border/50">
                    <th className="w-8" />
                    <th className="text-left py-1.5 pr-3 font-medium">Позиция</th>
                    <th className="text-left py-1.5 pr-3 font-medium">АЗС</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Было</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Станет</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Разница</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Маржа</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Продано</th>
                    <th className="text-right py-1.5 pr-3 font-medium">Эффект</th>
                    <th className="text-left py-1.5 font-medium">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {p.rows.map((r, i) => (
                    <tr key={`${r.station_id}-${r.item_uuid}-${i}`}
                        className="border-b border-border/30 hover:bg-accent/30">
                      <td className="py-1.5">
                        {!r.reject && (
                          <input type="checkbox"
                                 checked={выбраны.size === 0 || выбраны.has(r.item_uuid)}
                                 onChange={(e) => {
                                   const n = new Set(выбраны.size ? выбраны : поедут.map((x) => x.item_uuid))
                                   if (e.target.checked) n.add(r.item_uuid); else n.delete(r.item_uuid)
                                   setВыбраны(n)
                                 }} />
                        )}
                      </td>
                      <td className="py-1.5 pr-3 cursor-pointer" {...rowDrill({ sku: r.item_uuid, name: r.name })}>
                        {r.name}
                        {r.kvi && <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-muted text-muted-foreground"
                                        title="ключевая позиция: по ней покупатель судит об уровне цен">KVI</span>}
                      </td>
                      <td className="py-1.5 pr-3 text-muted-foreground">{r.station_id}</td>
                      <td className="py-1.5 pr-3 text-right">{fmtMoney(r.price)}</td>
                      <td className="py-1.5 pr-3 text-right font-medium">
                        {r.reject ? <span className="text-muted-foreground">—</span> : fmtMoney(r.new_price)}
                      </td>
                      <td className={`py-1.5 pr-3 text-right ${r.delta < 0 ? 'text-amber-500' : 'text-emerald-500'}`}>
                        {r.reject ? '—' : `${знак(r.delta)}${fmtMoney(r.delta)} (${знак(r.delta_pct)}${nf(r.delta_pct, 1)} %)`}
                      </td>
                      <td className="py-1.5 pr-3 text-right text-muted-foreground">
                        {r.margin != null ? `${nf(r.margin, 1)} %` : '—'}
                        {!r.reject && r.new_margin != null && ` → ${nf(r.new_margin, 1)} %`}
                      </td>
                      <td className="py-1.5 pr-3 text-right text-muted-foreground">{nf(r.qty, 1)}</td>
                      <td className="py-1.5 pr-3 text-right">{r.reject ? '—' : fmtMoney(r.effect)}</td>
                      <td className="py-1.5 text-muted-foreground">{r.reject || 'поедет'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
