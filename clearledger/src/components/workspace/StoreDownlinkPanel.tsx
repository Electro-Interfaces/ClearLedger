/**
 * «Магазин» → Станции → Задания станциям.
 *
 * Канал вниз: что центр приготовил для АЗС — карточки НСИ, цены, заготовки
 * приёмки, политика кассы, команды. Станция за CGNAT и забирает задания сама,
 * поэтому «отправлено» не значит «доехало»: между созданием и подтверждением
 * может пройти сколько угодно, и зависшее задание видно только отсюда.
 *
 * Два действия, которых раньше не было ни у кого, кроме доступа к базе:
 * отправить заново (снимаем отметки доставки — станция заберёт следующим
 * тактом, повтор идемпотентен) и снять с очереди. Отмена не притворяется
 * применением: у неё своё время и автор.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { RefreshCw, XCircle, ArrowDownToLine } from 'lucide-react'
import {
  getStoreDownlink, resendStoreDownlink, cancelStoreDownlink, resendStuckStoreDownlink,
  getStoreStations, type StoreDownlinkTask, type DownlinkState, type StoreStation,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'

const СОСТОЯНИЯ: { key: DownlinkState; подпись: string; cls: string }[] = [
  { key: 'ждёт станции', подпись: 'ждёт станции', cls: 'text-amber-300/90' },
  { key: 'доставлено', подпись: 'доставлено, нет подтверждения', cls: 'text-sky-300/90' },
  { key: 'применено', подпись: 'применено', cls: 'text-emerald-400/90' },
  { key: 'отменено', подпись: 'отменено', cls: 'text-muted-foreground' },
]

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU',
    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** Сколько задание уже ждёт — то, ради чего экран и открывают. */
function ждёт(t: StoreDownlinkTask): string {
  if (t.state === 'применено' || t.state === 'отменено') return '—'
  const мин = Math.round((Date.now() - new Date(t.created_at).getTime()) / 60000)
  if (мин < 60) return `${мин} мин`
  if (мин < 1440) return `${Math.round(мин / 60)} ч`
  return `${Math.round(мин / 1440)} сут`
}

export function StoreDownlinkPanel() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [станция, выбрать] = useState<number | null>(null)
  const [фильтр, задатьФильтр] = useState<DownlinkState | null>(null)

  const { data: парк } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
  })
  const станции = (парк?.stations ?? []) as StoreStation[]

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-downlink', company.id, станция],
    queryFn: () => getStoreDownlink(станция),
    refetchInterval: 60_000,
  })

  const обновить = () => qc.invalidateQueries({ queryKey: ['store-downlink'] })
  const переотправить = useMutation({
    mutationFn: resendStoreDownlink,
    onSuccess: () => { toast.success('Задание уйдёт станции следующим тактом'); обновить() },
    onError: (e: Error) => toast.error('Не удалось переотправить', { description: e.message }),
  })
  const переслатьЗависшие = useMutation({
    mutationFn: (station: number | null) => resendStuckStoreDownlink(station),
    onSuccess: (r) => {
      if (r.resent === 0) toast.info('Зависших заданий нет — всё подтверждено станцией')
      else toast.success(`Переотправлено заданий: ${r.resent}`)
      обновить()
    },
    onError: (e: Error) => toast.error('Не удалось переотправить', { description: e.message }),
  })
  const отменить = useMutation({
    mutationFn: cancelStoreDownlink,
    onSuccess: () => { toast.success('Задание снято с очереди'); обновить() },
    onError: (e: Error) => toast.error('Не удалось отменить', { description: e.message }),
  })

  const задания = (data?.tasks ?? []).filter((t) => !фильтр || t.state === фильтр)
  const занят = переотправить.isPending || отменить.isPending

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="text-base font-semibold">Задания станциям</h3>
        <p className="text-xs text-muted-foreground">
          Канал вниз: карточки НСИ, цены, заготовки приёмки, политика кассы. Станция забирает
          задания сама своим тактом — «отправлено» не значит «доехало». Зависшее задание можно
          отправить заново или снять с очереди.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {станции.length > 1 && (
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-muted-foreground">АЗС</span>
            <button type="button" onClick={() => выбрать(null)}
              className={`rounded-md border px-2 py-1 text-xs ${станция === null
                ? 'border-primary/60 bg-primary/10 text-foreground'
                : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
              все
            </button>
            {станции.map((s) => (
              <button key={s.station_id} type="button"
                onClick={() => выбрать(станция === s.station_id ? null : s.station_id)}
                className={`rounded-md border px-2 py-1 text-xs tabular-nums ${станция === s.station_id
                  ? 'border-primary/60 bg-primary/10 text-foreground'
                  : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
                {s.station_id}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-1.5">
          {СОСТОЯНИЯ.map((с) => {
            const сколько = data?.by_state?.[с.key] ?? 0
            const активен = фильтр === с.key
            return (
              <button key={с.key} type="button" disabled={сколько === 0}
                onClick={() => задатьФильтр(активен ? null : с.key)}
                aria-pressed={активен}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] ${активен
                  ? 'border-primary/60 bg-primary/15 text-foreground'
                  : сколько === 0
                    ? 'cursor-not-allowed border-border/40 text-muted-foreground/40'
                    : `border-border/60 hover:text-foreground ${с.cls}`}`}>
                {с.подпись} <span className="tabular-nums opacity-70">{сколько}</span>
              </button>
            )
          })}
        </div>

        {/* После долгого обрыва зависших заданий бывает много, и разбирать их
            поштучно — десятки нажатий. Кнопка трогает только доставленные без
            подтверждения старше получаса: свежие не задеваются, станция могла
            забрать задание минуту назад и как раз его применять. */}
        <button type="button" disabled={занят || переслатьЗависшие.isPending}
          onClick={() => переслатьЗависшие.mutate(станция)}
          className="ml-auto rounded-md border border-border/60 px-2.5 py-1 text-xs
                     text-muted-foreground hover:text-foreground disabled:opacity-50">
          Переслать зависшие{станция ? ` · АЗС ${станция}` : ''}
        </button>
      </div>

      {isLoading ? (
        <div className="text-sm text-muted-foreground">Загрузка очереди…</div>
      ) : error ? (
        <div className="text-sm text-red-400/90">Не удалось получить очередь заданий</div>
      ) : задания.length === 0 ? (
        <div className="flex items-start gap-3 rounded-lg border border-dashed border-border/50 p-5">
          <ArrowDownToLine className="mt-0.5 h-5 w-5 text-muted-foreground" />
          <div>
            <div className="text-sm">Очередь пуста</div>
            <div className="text-xs text-muted-foreground">
              Центр ничего не отправлял станциям{фильтр ? ` в состоянии «${фильтр}»` : ''}.
              Задания появляются сами: правка карточки или цены в «Каталоге» кладёт сюда
              полный снимок карточки.
            </div>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border/50">
          <table className="w-full text-xs">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Создано</th>
                <th className="px-3 py-2 text-left font-medium">АЗС</th>
                <th className="px-3 py-2 text-left font-medium">Что едет</th>
                <th className="px-3 py-2 text-left font-medium">Пояснение</th>
                <th className="px-3 py-2 text-left font-medium">Состояние</th>
                <th className="px-3 py-2 text-right font-medium">Ждёт</th>
                <th className="px-3 py-2 text-right font-medium">Действие</th>
              </tr>
            </thead>
            <tbody>
              {задания.map((t: StoreDownlinkTask) => {
                const с = СОСТОЯНИЯ.find((x) => x.key === t.state)
                return (
                  <tr key={t.id} className="border-t border-border/30">
                    <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground">{когда(t.created_at)}</td>
                    <td className="px-3 py-1.5 tabular-nums">{t.station_id}</td>
                    <td className="px-3 py-1.5">{t.label}</td>
                    <td className="max-w-[280px] truncate px-3 py-1.5 text-muted-foreground" title={t.note ?? ''}>
                      {t.note ?? '—'}
                    </td>
                    <td className={`px-3 py-1.5 ${с?.cls ?? ''}`}>
                      {t.state}
                      {t.state === 'применено' && (
                        <span className="ml-1.5 text-[10px] text-muted-foreground">{когда(t.acked_at)}</span>
                      )}
                      {t.state === 'отменено' && (
                        <span className="ml-1.5 text-[10px] text-muted-foreground">{когда(t.cancelled_at)}</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{ждёт(t)}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex justify-end gap-1.5">
                        <Button size="sm" variant="outline" disabled={занят}
                          onClick={() => переотправить.mutate(t.id)}
                          title="Снять отметки доставки — станция заберёт задание следующим тактом">
                          <RefreshCw className="mr-1 h-3 w-3" />заново
                        </Button>
                        <Button size="sm" variant="ghost"
                          disabled={занят || t.state === 'применено' || t.state === 'отменено'}
                          onClick={() => отменить.mutate(t.id)}
                          title={t.state === 'применено'
                            ? 'Станция уже применила задание'
                            : 'Снять задание с очереди станции'}>
                          <XCircle className="mr-1 h-3 w-3" />снять
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[10px] text-muted-foreground/60">
        Вниз едет полный снимок карточки, а не изменённое поле: станция могла пропустить
        предыдущую правку, и дельта «только новая цена» оставила бы её со старым названием.
        Поэтому повторная отправка безопасна.
      </p>
    </div>
  )
}
