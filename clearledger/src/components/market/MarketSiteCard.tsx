/**
 * Паспорт станции рынка: всё, что о ней известно, на одном экране.
 *
 * Парсер привозит по каждой точке полсотни полей — координаты, разъёмы с их
 * мощностями, качество связи, долю успешных зарядок, оценку с числом отзывов,
 * тарифные окна, снимки площадки. В списке из этого помещалось семь колонок, и
 * остальное лежало в базе без дела: сравнить свою станцию с чужой было не с чем
 * (замечание МАГа 13.09.2026).
 *
 * Правило подачи здесь одно: пустое поле — «нет данных», а не ноль и не прочерк
 * без объяснения. Заполненность у источника неравномерная, и там, где её нет,
 * честнее сказать об этом словом.
 */
import { useState } from 'react'
import { ArrowLeft, ExternalLink, MapPin } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import type { MarketSite } from '@/services/marketService'

const nf = new Intl.NumberFormat('ru-RU')
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

const КЛАСС: Record<string, string> = {
  network: 'сеть',
  independent: 'независимая точка',
  home: 'домашняя розетка',
  unknown: 'класс не определён',
}

const СТАТУС: Record<string, string> = {
  active: 'работает',
  closed: 'закрыта',
  planned: 'в планах',
}

/** Значение с честным «нет данных» вместо прочерка. */
function Знач({ v, unit, digits = 0 }: {
  v: number | string | null | undefined
  unit?: string
  digits?: number
}) {
  if (v === null || v === undefined || v === '') {
    return <span className="text-muted-foreground">нет данных</span>
  }
  const текст = typeof v === 'number'
    ? (digits ? nf1.format(v) : nf.format(v))
    : v
  return <span className="tabular-nums">{текст}{unit ? ` ${unit}` : ''}</span>
}

function Поле({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  )
}

/** Возраст последней зарядки: по нему видно, жива станция или только числится. */
function возраст(iso: string | null): { text: string; stale: boolean } {
  if (!iso) return { text: 'зарядок не видели ни разу', stale: true }
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return { text: 'заряжали сегодня', stale: false }
  if (days === 1) return { text: 'заряжали вчера', stale: false }
  if (days < 90) return { text: `заряжали ${days} дн назад`, stale: false }
  return { text: `последняя зарядка ${days} дн назад`, stale: true }
}

export function MarketSiteCard({ site, onBack }: { site: MarketSite; onBack: () => void }) {
  const [фото, setФото] = useState(false)
  const live = возраст(site.lastSessionAt)
  const coords = site.lat != null && site.lon != null
    ? `${site.lat.toFixed(5)}, ${site.lon.toFixed(5)}` : null
  const connectors = site.connectorsJson ?? []

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-4">
      <button type="button" onClick={onBack}
        className="flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3.5" aria-hidden /> ко всем точкам
      </button>

      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-headline text-base font-semibold">{site.name}</span>
            <span className="text-xs text-muted-foreground">
              {КЛАСС[site.siteClass] ?? site.siteClass}
              {' · '}{СТАТУС[site.status] ?? site.status}
              {site.isOurs && <span className="ml-1 text-primary">· наша станция</span>}
            </span>
          </div>

          <div className="grid gap-x-6 gap-y-3 md:grid-cols-3 xl:grid-cols-4">
            <Поле label="оператор">
              <Знач v={site.operatorName} />
            </Поле>
            <Поле label="адрес">
              <Знач v={site.address ?? site.city} />
            </Поле>
            <Поле label="координаты">
              {coords ? (
                <span className="flex items-center gap-1">
                  <MapPin className="size-3.5 text-muted-foreground" aria-hidden />
                  <span className="tabular-nums">{coords}</span>
                </span>
              ) : <Знач v={null} />}
            </Поле>
            <Поле label="регион">
              <Знач v={site.region} />
            </Поле>
            <Поле label="постов / портов">
              <Знач v={site.ports} />
              {site.connectorsTotal != null && site.connectorsTotal !== site.ports && (
                <span className="text-muted-foreground"> · разъёмов {site.connectorsTotal}</span>
              )}
            </Поле>
            <Поле label="мощность">
              <Знач v={site.maxPowerKw} unit="кВт" digits={1} />
            </Поле>
            <Поле label="тип тока">
              <Знач v={site.currentType} />
            </Поле>
            <Поле label="цена">
              {site.price?.value != null ? (
                <>
                  <span className="tabular-nums">
                    {nf1.format(site.price.value)} ₽{site.price.unit === 'kwh' ? '/кВт·ч' : ''}
                  </span>
                  {site.price.basis && (
                    <span className="text-muted-foreground"> · {site.price.basis}</span>
                  )}
                </>
              ) : <Знач v={null} />}
            </Поле>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="text-xs font-semibold">Как станция работает</div>
          <div className="grid gap-x-6 gap-y-3 md:grid-cols-3 xl:grid-cols-4">
            <Поле label="последняя зарядка">
              <span className={live.stale ? 'text-warning' : ''}>{live.text}</span>
            </Поле>
            <Поле label="связь за сутки">
              <Знач v={site.quality24h} unit="%" digits={1} />
            </Поле>
            <Поле label="успешных зарядок">
              <Знач v={site.successPct} unit="%" digits={1} />
            </Поле>
            <Поле label="оценка">
              {site.rating != null ? (
                <>
                  <span className="tabular-nums">{nf1.format(site.rating)}</span>
                  <span className="text-muted-foreground">
                    {' '}по {nf.format(site.reviews ?? 0)} отзывам
                  </span>
                </>
              ) : <Знач v={null} />}
            </Поле>
          </div>
          {(site.closedConfirmations ?? 0) > 0 && (
            <p className="text-xs text-warning">
              Закрытие подтверждали {site.closedConfirmations} раз — станции может уже
              не быть на месте.
            </p>
          )}
        </CardContent>
      </Card>

      {connectors.length > 0 && (
        <Card>
          <CardContent className="space-y-2 p-4">
            <div className="text-xs font-semibold">Разъёмы</div>
            {/* Тип разъёма решает, подъедет ли сюда машина вообще: с CCS не
                зарядиться от GB/T, сколько бы киловатт там ни было. */}
            <div className="flex flex-wrap gap-2">
              {connectors.map((c, i) => (
                <span key={`${c.type}-${i}`}
                  className="rounded-md border border-border px-2 py-1 text-xs">
                  {c.type ?? 'тип не указан'}
                  {c.power_kw != null && (
                    <span className="ml-1 tabular-nums text-muted-foreground">
                      {nf1.format(c.power_kw)} кВт
                    </span>
                  )}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {(site.photoCount ?? 0) > 0 && (
        <Card>
          <CardContent className="space-y-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-semibold">
                Снимки площадки · {nf.format(site.photoCount ?? 0)}
              </span>
              <span className="text-xs text-muted-foreground">
                {site.photoAuthors
                  ? `сняли: ${site.photoAuthors.split('|').slice(0, 4).join(', ')}`
                  : 'авторы не указаны'}
              </span>
            </div>
            {/* Снимки грузятся с сайта источника: файлы лежат у него, и ссылка может
                перестать открываться. Поэтому показываем их по кнопке, а число
                снимков храним отдельно — по нему видно, что они были. */}
            {!фото ? (
              <button type="button" onClick={() => setФото(true)}
                className="rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-accent">
                Показать снимки
              </button>
            ) : (
              <div className="flex flex-wrap gap-2">
                {(site.photos ?? []).slice(0, 12).map((url) => (
                  <a key={url} href={url} target="_blank" rel="noreferrer noopener"
                    className="block">
                    <img src={url} alt="" loading="lazy"
                      className="h-24 w-32 rounded-md border border-border object-cover" />
                  </a>
                ))}
                {(site.photos?.length ?? 0) > 12 && (
                  <span className="self-center text-xs text-muted-foreground">
                    и ещё {(site.photos?.length ?? 0) - 12}
                  </span>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-1 p-4 text-xs text-muted-foreground">
          <div className="text-xs font-semibold text-foreground">Откуда мы это знаем</div>
          <div>
            источник: {site.source}
            {site.externalId && ` · номер в источнике ${site.externalId}`}
          </div>
          <div>
            впервые увидели:{' '}
            {site.firstSeenAt ? new Date(site.firstSeenAt).toLocaleDateString('ru-RU') : 'нет данных'}
            {' · '}в последнем срезе:{' '}
            {site.lastSeenAt ? new Date(site.lastSeenAt).toLocaleDateString('ru-RU') : 'нет данных'}
          </div>
          {site.notes && <div>заметка источника: {site.notes}</div>}
          {coords && (
            <a href={`https://yandex.ru/maps/?pt=${site.lon},${site.lat}&z=17&l=map`}
              target="_blank" rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-primary hover:underline">
              открыть на Яндекс.Картах <ExternalLink className="size-3" aria-hidden />
            </a>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
