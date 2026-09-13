/**
 * «Компании» — кто на рынке и что он делает (docs/MARKET-ROADMAP.md §9, этап 2).
 *
 * Вопрос экрана не «сколько у него станций», а «стоит ли его бояться и где».
 * Поэтому в строке сразу та рамка, в которой сравнивают сети: точки и порты, живые
 * из них, цена, связь, репутация. Сорок мёртвых розеток и десять работающих DC —
 * не одно и то же, хотя «точек» у первого больше.
 *
 * Карточка отвечает на «что он делает»: где стоит, чем оснащён, почём заряжает, как
 * его оценивают и где он рос последние полтора года.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Building2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { useCompany } from '@/contexts/CompanyContext'
import {
  getMarketOperatorCard, listMarketOperators, type MarketOperatorCard,
} from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

/** Уровни достоверности из Marketing/research/data-quality.md. */
const УРОВЕНЬ: Record<number, string> = {
  1: 'данные проверяемы',
  2: 'внутренняя оценка',
  3: 'сигнал, требует проверки',
}

const RELATION_LABEL: Record<string, string> = {
  competitor: 'конкурент',
  partner: 'партнёр',
  own: 'наша сеть',
  other: 'прочие',
}

const ВИДЫ = [
  { k: 'cities', label: 'Где стоит' },
  { k: 'power', label: 'Чем оснащён' },
  { k: 'months', label: 'Как рос' },
  { k: 'sites', label: 'Точки' },
] as const

/** Число или честное «нет данных». Ноль вместо пропуска — ложь, которая читается
 *  как факт: в публичном реестре половина полей не заполнена. */
function Value({ v, unit, digits = 0 }: { v: number | null | undefined; unit?: string; digits?: number }) {
  if (v == null) return <span className="text-muted-foreground">нет данных</span>
  const formatted = digits ? nf1.format(v) : nf.format(v)
  return <span className="tabular-nums">{formatted}{unit ? ` ${unit}` : ''}</span>
}

/** Горизонтальная полоса ряда — вместо графика там, где рядов мало и важны числа. */
function Bars({ rows, max }: { rows: { label: string; value: number }[]; max: number }) {
  return (
    <ul className="space-y-1">
      {rows.map((r) => (
        <li key={r.label} className="flex items-center gap-2 text-xs">
          <span className="w-40 shrink-0 truncate text-muted-foreground">{r.label}</span>
          <span className="h-2 min-w-[2px] rounded-sm bg-primary"
            style={{ width: `${Math.max(2, (r.value / Math.max(1, max)) * 60)}%` }} aria-hidden />
          <span className="tabular-nums">{nf.format(r.value)}</span>
        </li>
      ))}
    </ul>
  )
}

function CompanyCard({ card, onBack }: { card: MarketOperatorCard; onBack: () => void }) {
  const [вид, setВид] = useState<string>('cities')
  const t = card.totals
  return (
    <div className="space-y-3">
      <button type="button" onClick={onBack}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3.5" aria-hidden /> ко всем компаниям
      </button>

      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-headline text-base font-semibold">{card.name}</span>
            <span className="text-xs text-muted-foreground">
              {RELATION_LABEL[card.relation] ?? card.relation}
              {card.siteUrl && (
                <> · <a href={`https://${card.siteUrl.replace(/^https?:\/\//, '')}`}
                  target="_blank" rel="noreferrer noopener"
                  className="underline decoration-dotted underline-offset-2">
                  {card.siteUrl}
                </a></>
              )}
            </span>
          </div>

          {/* Чем компания является: разговор с агрегатором на чужой платформе и с
              владельцем сети — это два разных разговора. Пометка «не проверено»
              обязательна: класс проставлен разбором, а не человеком. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            {card.class && (
              <span>
                <span className="text-muted-foreground">модель: </span>
                <span className="font-medium">{card.class}</span>
                {!card.classChecked && (
                  <span className="text-muted-foreground"> · не проверено</span>
                )}
              </span>
            )}
            {/* Уровень достоверности всей записи. Компания, известная только по
                волонтёрской карте, и компания из основного источника — разного
                веса, и по ним нельзя решать одинаково. */}
            {card.dataLevel != null && (
              <span className={card.dataLevel === 1 ? 'text-success'
                : card.dataLevel === 3 ? 'text-warning' : 'text-muted-foreground'}>
                {УРОВЕНЬ[card.dataLevel]}
              </span>
            )}
            {card.baseCity && (
              <span className="text-muted-foreground">
                база: <span className="text-foreground">{card.baseCity}</span>
              </span>
            )}
            {card.citiesCount != null && (
              <span className="text-muted-foreground">
                городов {nf.format(card.citiesCount)}
                {card.districts != null && `, округов ${card.districts}`}
              </span>
            )}
            {card.platformCode && (
              <span className="text-muted-foreground">
                платформа: <span className="text-foreground">{card.platformCode}</span>
                {card.platformOwner && card.platformOwner !== card.name
                  && ` (${card.platformOwner})`}
                {card.ownPlatform === true && ' · своя'}
              </span>
            )}
            <span className="text-muted-foreground">
              роуминг:{' '}
              {card.roaming === true ? <span className="text-success">открыт</span>
                : card.roaming === false ? 'только своё приложение'
                : 'нет данных'}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <div>
              <div className="text-xs text-muted-foreground">точек сети</div>
              <div className="text-sm font-semibold"><Value v={t.sites} /></div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">портов</div>
              <div className="text-sm font-semibold"><Value v={t.ports} /></div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">заряжали за 90 дн</div>
              <div className="text-sm font-semibold"><Value v={t.alive} /></div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">медиана цены</div>
              <div className="text-sm font-semibold">
                <Value v={t.medianPricePerKwh} unit="₽/кВт·ч" digits={1} />
              </div>
              <div className="text-xs text-muted-foreground">по {t.pricedSites} наблюдениям</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">связь за сутки</div>
              <div className="text-sm font-semibold"><Value v={t.quality} unit="%" digits={1} /></div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">успешных зарядок</div>
              <div className="text-sm font-semibold"><Value v={t.success} unit="%" digits={1} /></div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">оценка</div>
              <div className="text-sm font-semibold"><Value v={t.rating} digits={1} /></div>
              <div className="text-xs text-muted-foreground">{nf.format(t.reviews)} отзывов</div>
            </div>
          </div>
          {/* Реквизиты и контакты. Показываем всегда, ссылаться можно только на
              подтверждённые: бренд и юрлицо часто не совпадают, и ошибиться здесь
              дороже, чем промолчать. Формулировку достоверности даём как есть —
              в ней больше смысла, чем в «да/нет». */}
          <div className="grid gap-x-6 gap-y-1 border-t border-border/60 pt-3 text-xs md:grid-cols-2">
            <div>
              <span className="text-muted-foreground">юрлицо: </span>
              {card.legalName ? (
                <>
                  <span className={card.legalTrusted ? '' : 'text-muted-foreground'}>
                    {card.legalName}
                  </span>
                  {card.legalConfidence && (
                    <span className={card.legalTrusted ? 'text-success' : 'text-warning'}>
                      {' '}· {card.legalConfidence}
                    </span>
                  )}
                </>
              ) : <span className="text-muted-foreground">не найдено</span>}
            </div>
            <div>
              <span className="text-muted-foreground">ИНН / ОГРН: </span>
              {card.inn || card.ogrn ? (
                <span className={card.legalTrusted ? 'tabular-nums'
                  : 'tabular-nums text-muted-foreground line-through decoration-dotted'}>
                  {card.inn ?? '—'} / {card.ogrn ?? '—'}
                </span>
              ) : <span className="text-muted-foreground">нет данных</span>}
              {card.legalStatus && (
                <span className={card.legalStatus === 'действует'
                  ? 'text-success' : 'text-warning'}> · {card.legalStatus}</span>
              )}
            </div>
            <div>
              <span className="text-muted-foreground">руководитель: </span>
              {card.director ?? <span className="text-muted-foreground">нет данных</span>}
            </div>
            <div>
              <span className="text-muted-foreground">адрес: </span>
              {card.legalAddress ?? card.publicAddress
                ?? <span className="text-muted-foreground">нет данных</span>}
            </div>
            <div>
              <span className="text-muted-foreground">телефон: </span>
              {card.phone ?? <span className="text-muted-foreground">нет данных</span>}
            </div>
            <div>
              <span className="text-muted-foreground">приложение: </span>
              {card.appName ? (
                <>
                  {card.appName}
                  {card.appRating != null && (
                    <span className="text-muted-foreground">
                      {' '}· {nf1.format(card.appRating)}
                      {card.appReviews != null && ` по ${nf.format(card.appReviews)} отзывам`}
                    </span>
                  )}
                </>
              ) : <span className="text-muted-foreground">не нашли</span>}
            </div>
          </div>

          {!card.legalTrusted && (card.inn || card.legalName) && (
            <p className="text-xs text-warning">
              Реквизиты не подтверждены — ссылаться на них в документах и письмах
              нельзя. Бренд и юрлицо часто не совпадают, а однофамильцы в ЕГРЮЛ
              встречаются постоянно: это версия для проверки, а не реквизиты
              компании.
            </p>
          )}

          {/* Откуда мы вообще знаем эту компанию: одна выгрузка не видит рынок
              целиком, и компания из одного упоминания надёжна иначе, чем найденная
              тремя источниками. */}
          {(card.sourceCount || card.pointsTotal) && (
            <p className="text-xs text-muted-foreground">
              {card.pointsTotal != null && `точек по всем источникам ${nf.format(card.pointsTotal)}`}
              {card.pointsRegistry != null && `, в основной выгрузке ${nf.format(card.pointsRegistry)}`}
              {(card.pointsOsm ?? 0) > 0 && `, только в OpenStreetMap ${nf.format(card.pointsOsm!)}`}
              {card.sources && `. Источники: ${card.sources}`}
              {(card.cardsYandex ?? 0) > 0 && `. Отдельно: ${nf.format(card.cardsYandex!)} карточек в справочнике организаций — это упоминания, а не точки, и к числу станций их не прибавляют`}
              {card.publicRating != null && `. Публичная оценка сети ${nf1.format(card.publicRating)}`}
              {card.publicReviews != null && ` по ${nf.format(card.publicReviews)} отзывам`}
            </p>
          )}

          {(t.planned > 0 || t.closed > 0 || t.homeSockets > 0) && (
            <p className="text-xs text-muted-foreground">
              {t.planned > 0 && `в планах ${t.planned}. `}
              {t.closed > 0 && `закрыто ${t.closed}. `}
              {t.homeSockets > 0 && `домашних розеток под этим именем ${t.homeSockets} — в счёт сети не идут.`}
            </p>
          )}
        </CardContent>
      </Card>

      <PanelViewTabs tabs={ВИДЫ} value={вид} onChange={setВид} />

      <Card>
        <CardContent className="p-4">
          {вид === 'cities' && (
            <Bars rows={card.cities.map((c) => ({ label: c.name, value: c.sites }))}
              max={Math.max(...card.cities.map((c) => c.sites), 1)} />
          )}
          {вид === 'power' && (
            <Bars rows={card.power.map((p) => ({ label: p.bucket, value: p.sites }))}
              max={Math.max(...card.power.map((p) => p.sites), 1)} />
          )}
          {вид === 'months' && (
            <div className="space-y-2">
              <Bars rows={card.months.map((m) => ({ label: m.month, value: m.sites }))}
                max={Math.max(...card.months.map((m) => m.sites), 1)} />
              <p className="text-xs text-muted-foreground">
                Месяц — это когда точка ПОЯВИЛАСЬ В ИСТОЧНИКЕ, а не когда её построили:
                публичная карта завела большую часть записей разом при своём запуске,
                и всплеск 2022 года — её история, а не стройка конкурента. Для решения
                годится правая часть ряда: последние месяцы источник ведёт по факту.
              </p>
            </div>
          )}
          {вид === 'sites' && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-1 text-left font-medium">Точка</th>
                    <th className="py-1 text-left font-medium">Город</th>
                    <th className="py-1 text-right font-medium">Портов</th>
                    <th className="py-1 text-right font-medium">кВт</th>
                    <th className="py-1 text-left font-medium">Ток</th>
                    <th className="py-1 text-right font-medium">Связь</th>
                    <th className="py-1 text-right font-medium">Оценка</th>
                    <th className="py-1 text-left font-medium">Спрос</th>
                  </tr>
                </thead>
                <tbody>
                  {card.sites.map((s) => (
                    <tr key={s.id} className="border-t border-border/40">
                      <td className="py-1">{s.name}</td>
                      <td className="py-1 text-muted-foreground">{s.city ?? '—'}</td>
                      <td className="py-1 text-right"><Value v={s.ports} /></td>
                      <td className="py-1 text-right"><Value v={s.maxPowerKw} digits={1} /></td>
                      <td className="py-1 text-muted-foreground">{s.currentType ?? '—'}</td>
                      <td className="py-1 text-right"><Value v={s.quality} unit="%" digits={1} /></td>
                      <td className="py-1 text-right"><Value v={s.rating} digits={1} /></td>
                      <td className="py-1 text-muted-foreground">
                        {s.lastSessionAt ? (s.alive ? 'заряжали недавно' : 'молчит') : 'нет данных'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * `initialOpen` и `onBack` нужны, когда экран открыт не сам по себе, а из расклада
 * сил: там уже выбрана сеть, и возврат должен вести обратно в расклад, а не в
 * список компаний, которого человек в этом пути не видел.
 */
export function MarketCompaniesPanel({ initialOpen = null, onBack }: {
  initialOpen?: string | null
  onBack?: () => void
} = {}) {
  const { companyId } = useCompany()
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(initialOpen)

  const list = useQuery({
    queryKey: ['market-operators', companyId],
    queryFn: () => listMarketOperators(companyId),
    enabled: !!companyId,
  })
  const card = useQuery({
    queryKey: ['market-operator-card', companyId, open],
    queryFn: () => getMarketOperatorCard(companyId, open as string),
    enabled: !!companyId && !!open,
  })

  if (list.isLoading) {
    return (
      <div className="space-y-2 p-4" aria-busy="true">
        <span className="sr-only">Считаем компании рынка</span>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-10 animate-pulse rounded-lg border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  if (open && card.data) {
    return (
      <div className="h-full overflow-auto p-4">
        <CompanyCard card={card.data} onBack={() => (onBack ? onBack() : setOpen(null))} />
      </div>
    )
  }

  const rows = (list.data?.operators ?? []).filter(
    (o) => !q || o.name.toLowerCase().includes(q.toLowerCase()))
  const networks = rows.filter((o) => o.sites > 0)
  const leader = networks[0]

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="flex items-center gap-2 text-sm">
            <Building2 className="size-4 text-primary" aria-hidden />
            <span className="font-medium">
              {networks.length === 0
                ? 'Компаний с точками пока нет — рынок наполняется выгрузкой реестра.'
                : `На рынке ${networks.length} компаний с точками; крупнейшая — ${leader.name} (${nf.format(leader.sites)}).`}
            </span>
          </span>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Компания"
            className="h-8 w-[200px] text-xs" />
        </CardContent>
      </Card>

      <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-muted/60 text-muted-foreground">
            <tr>
              <th className="p-2 text-left font-medium">Компания</th>
              <th className="p-2 text-left font-medium">Отношение</th>
              <th className="p-2 text-right font-medium">Точек</th>
              <th className="p-2 text-right font-medium">Живых</th>
              <th className="p-2 text-right font-medium">Портов</th>
              <th className="p-2 text-right font-medium">Медиана ₽/кВт·ч</th>
              <th className="p-2 text-right font-medium">Связь</th>
              <th className="p-2 text-right font-medium">Оценка</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => (
              <tr key={o.id} onClick={() => setOpen(o.id)}
                className="cursor-pointer border-t border-border/60 hover:bg-accent/40">
                <td className="p-2 font-medium">{o.name}</td>
                <td className="p-2 text-muted-foreground">
                  {RELATION_LABEL[o.relation] ?? o.relation}
                </td>
                <td className="p-2 text-right"><Value v={o.sites} /></td>
                <td className="p-2 text-right"><Value v={o.alive} /></td>
                <td className="p-2 text-right"><Value v={o.ports} /></td>
                <td className="p-2 text-right">
                  <Value v={o.medianPricePerKwh} digits={1} />
                </td>
                <td className="p-2 text-right"><Value v={o.quality} unit="%" digits={1} /></td>
                <td className="p-2 text-right"><Value v={o.rating} digits={1} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="p-8 text-center text-sm text-muted-foreground">
            Компаний пока нет. Они заводятся вместе с точками — выгрузкой реестра или
            вручную.
          </p>
        )}
      </div>
    </div>
  )
}
