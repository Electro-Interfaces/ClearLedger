/**
 * «Магазин» → Станции → Сверка с 1С.
 *
 * Пока 1С ведёт учёт станции параллельно, её пакеты приходят тем же каналом —
 * и это единственная возможность доказать, что агент считает правильно. Экран
 * отвечает на два вопроса разом:
 *
 *   — сходится ли КАЖДАЯ смена (теневая сверка агент ↔ 1С) и сколько чистых
 *     дней подряд набралось: критерий этапа — четырнадцать подряд и свежих,
 *     а не «сколько-то совпало за всё время»;
 *   — все ли ВИДЫ документов мы уже умеем: 1С делает оприходования и
 *     перемещения, которых Ledger может ещё не порождать, и это вопрос охвата,
 *     а не точности.
 *
 * Данные: /api/store/reconcile (edge_service.reconcile) и /api/store/parity.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Download, RadioTower } from 'lucide-react'
import {
  getStoreStations, getStoreReconcile, getStoreParity,
  type StoreStation, type StoreReconcileShift,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { rowDrill } from './rowDrill'
import { csvDownload } from './csvDownload'

const СТАТУС: Record<string, string> = {
  'совпало': 'text-emerald-400/90',
  'расхождение': 'text-red-400/90',
  'нет пары': 'text-muted-foreground',
  'нет данных': 'text-muted-foreground/70',
}

function когда(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  // Битая дата даёт «Invalid Date» посреди таблицы — прочерк честнее.
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

/** Строка сверки: причины расхождения раскрываются, а не висят в таблице. */
function СменаСтрока({ s }: { s: StoreReconcileShift }) {
  const [открыта, открыть] = useState(false)
  const причины = s.issues ?? []
  const есть = причины.length > 0
  return (
    <>
      {/* Раскрытие — общим хелпером: строка берётся и мышью, и с клавиатуры.
          Раньше `onClick` висел прямо на `tr`, и причины расхождения были
          недостижимы без мыши. */}
      <tr {...rowDrill(есть ? () => открыть(!открыта) : null,
                       `Смена ${s.shift ?? ''} — показать расхождения`,
                       'border-t border-border/30', открыта)}>
        <td className="px-3 py-1.5">
          {есть && <ChevronRight className={`mr-1 inline h-3 w-3 transition-transform ${открыта ? 'rotate-90' : ''}`} />}
          {когда(s.closed_at ?? s.opened_at)}
        </td>
        <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{s.shift ?? '—'}</td>
        <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{s.station}</td>
        <td className={`px-3 py-1.5 ${СТАТУС[s.status] ?? ''}`}>{s.status}</td>
        <td className="px-3 py-1.5 text-muted-foreground">
          {s.detail ?? s.note ?? (есть ? `${причины.length} расхождений` : '—')}
        </td>
      </tr>
      {открыта && есть && (
        <tr className="bg-background/40">
          <td colSpan={5} className="px-3 py-2">
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {причины.map((p, i) => <li key={i}>· {p}</li>)}
            </ul>
          </td>
        </tr>
      )}
    </>
  )
}

export function StoreParityPanel() {
  const { company } = useCompany()
  const [станция, выбрать] = useState<number | null>(null)

  const { data: парк } = useQuery({
    queryKey: ['store-stations', company.id],
    queryFn: getStoreStations,
  })
  const станции = (парк?.stations ?? []) as StoreStation[]
  useEffect(() => {
    if (станция === null && станции.length > 0) выбрать(станции[0].station_id)
  }, [станция, станции])

  const { data: сверка, isLoading, error, refetch } = useQuery({
    queryKey: ['store-reconcile', company.id, станция],
    queryFn: () => getStoreReconcile(станция),
    enabled: станция !== null,
  })
  const { data: паритет } = useQuery({
    queryKey: ['store-parity', company.id, станция],
    queryFn: () => getStoreParity(станция as number),
    enabled: станция !== null,
  })

  const кр = сверка?.criterion
  const прогресс = кр ? Math.min(100, Math.round((кр.days / Math.max(1, кр.target_days)) * 100)) : 0
  // Свежесть важнее обрыва: серия, оборвавшаяся месяц назад, и серия, которая
  // просто не продолжается неделю, — разные новости, и вторая сейчас важнее.
  const несвежая = (кр?.stale ?? 0) > 0

  // Пока сверка не пришла, критерий не показывается вовсе. Раньше рисовался
  // «0 из 14 · серия ещё не начиналась» — при каждом открытии экран сначала
  // сообщал, что доказательства нет.
  if (error) {
    return (
      <div className="space-y-4 p-6">
        <h3 className="text-base font-semibold">Сверка с 1С</h3>
        <div className="text-sm text-red-400/90">
          Не удалось получить сверку — это сбой запроса, а не отсутствие данных.{' '}
          <button type="button" className="underline underline-offset-2" onClick={() => refetch()}>
            Повторить
          </button>
        </div>
      </div>
    )
  }

  const выгрузить = () => csvDownload(
    `сверка-с-1с-${станция ?? 'сеть'}`,
    ['Дата', 'Смена', 'АЗС', 'Статус', 'Подробность', 'Расхождений'],
    (сверка?.shifts ?? []).map((s) => [
      когда(s.closed_at ?? s.opened_at), s.shift ?? '', s.station,
      s.status, s.detail ?? s.note ?? '', (s.issues ?? []).length,
    ]))

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">Сверка с 1С</h3>
          <p className="text-xs text-muted-foreground">
            Пока 1С считает станцию параллельно, её пакеты приходят тем же каналом. Сходимость
            каждой смены доказывает, что агент считает верно; паритет видов документов показывает,
            чего мы ещё не умеем. Вместе это условие вывода 1С из контура станции.
          </p>
        </div>
        {/* Доказательство сходимости нужно предъявлять, а не пересказывать. */}
        {(сверка?.shifts?.length ?? 0) > 0 && (
          <button type="button" onClick={выгрузить}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border/60 px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground">
            <Download className="size-3.5" />Выгрузить сверку
          </button>
        )}
      </div>

      {станции.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {станции.map((s) => (
            <button key={s.station_id} type="button" onClick={() => выбрать(s.station_id)}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs tabular-nums ${
                станция === s.station_id
                  ? 'border-primary/60 bg-primary/10 text-foreground'
                  : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>
              <RadioTower className="h-3.5 w-3.5" />АЗС {s.station_id}
            </button>
          ))}
        </div>
      )}

      {/* Критерий этапа: непрерывность и свежесть, а не сумма совпадений */}
      <div className="rounded-lg border border-border/50 bg-card/40 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="text-sm font-medium">
            Чистых дней подряд:{' '}
            <span className={`tabular-nums ${кр?.met ? 'text-emerald-400/90' : ''}`}>
              {кр ? кр.days : '—'}
            </span>
            <span className="text-muted-foreground"> из {кр?.target_days ?? 14}</span>
            {/* Выполнение критерия — словами, а не одним зелёным цветом:
                иначе главный ответ экрана недоступен без цветового зрения. */}
            {кр && (
              <span className={`ml-2 text-xs font-normal ${кр.met ? 'text-emerald-400/90' : 'text-muted-foreground'}`}>
                {кр.met ? '· критерий выполнен' : '· критерий не выполнен'}
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground">
            {isLoading ? 'считаем серию…'
              : кр?.from ? `окно ${когда(кр.from)} — ${когда(кр.to)}` : 'серия ещё не начиналась'}
          </div>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div className={`h-full ${кр?.met ? 'bg-emerald-500/80' : несвежая ? 'bg-amber-500/70' : 'bg-primary/70'}`}
               style={{ width: `${прогресс}%` }} />
        </div>
        <div className="mt-2 text-xs text-muted-foreground">
          {/* Несвежесть идёт первой: серия может быть длинной и оборванной год
              назад, но если сверки нет неделю — новость именно эта. Раньше ветка
              «несвежая» была недостижима, потому что обрыв есть почти всегда. */}
          {несвежая
            ? <>последний сверенный день — {когда(кр?.to)}, отставание {кр?.stale} дн.: сверка не идёт{' '}
                {кр?.broken_by && <>(до этого серию оборвал {когда(кр.broken_by.дата)} — {кр.broken_by.статус})</>}</>
            : кр?.broken_by
              ? <>серию оборвал {когда(кр.broken_by.дата)} — {кр.broken_by.статус}</>
              : 'дни обязаны идти подряд по календарю и заканчиваться сегодняшним днём'}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Сверено смен</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums">{сверка?.shifts_compared ?? 0}</div>
          {/* Окно запроса — часть цифры: строки «нет пары» занимают в нём место
              наравне со сверенными, и потолок молча срезает доказательство. */}
          {сверка?.total != null && сверка.limit != null && сверка.total > сверка.limit && (
            <div className="mt-0.5 text-[11px] text-muted-foreground">
              показаны {сверка.limit} последних смен из {сверка.total}
            </div>
          )}
        </div>
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Совпало</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums text-emerald-400/90">{сверка?.matched ?? 0}</div>
        </div>
        <div className="rounded-lg border border-border/50 bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">Расхождений</div>
          <div className={`mt-0.5 text-xl font-semibold tabular-nums ${(сверка?.mismatched ?? 0) > 0 ? 'text-red-400/90' : ''}`}>
            {сверка?.mismatched ?? 0}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Дата</th>
              <th className="px-3 py-2 text-left font-medium">Смена</th>
              <th className="px-3 py-2 text-left font-medium">АЗС</th>
              <th className="px-3 py-2 text-left font-medium">Статус</th>
              <th className="px-3 py-2 text-left font-medium">Что не сошлось</th>
            </tr>
          </thead>
          <tbody>
            {(сверка?.shifts ?? []).map((s, i) => <СменаСтрока key={`${s.shift}-${i}`} s={s} />)}
          </tbody>
        </table>
        {!isLoading && (сверка?.shifts?.length ?? 0) === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Пар «агент ↔ 1С» пока нет: сверять можно только смены, выгруженные обеими сторонами.
          </div>
        )}
        {isLoading && <div className="px-3 py-6 text-center text-sm text-muted-foreground">Сверяем смены…</div>}
      </div>

      {/* Паритет видов документов: вопрос охвата, а не точности */}
      {паритет && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="text-sm font-medium">Виды документов</div>
            <div className="text-xs text-muted-foreground">
              умеем {паритет.covered} · не умеем {паритет.missing} · за последние {паритет.days} дн.
            </div>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border/50">
            <table className="w-full text-xs">
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Документ</th>
                  <th className="px-3 py-2 text-right font-medium">1С всего</th>
                  <th className="px-3 py-2 text-right font-medium">1С за период</th>
                  <th className="px-3 py-2 text-left font-medium">Последний из 1С</th>
                  <th className="px-3 py-2 text-right font-medium">Ledger всего</th>
                  <th className="px-3 py-2 text-right font-medium">Ledger за период</th>
                  <th className="px-3 py-2 text-left font-medium">Последний наш</th>
                  <th className="px-3 py-2 text-left font-medium">Охват</th>
                </tr>
              </thead>
              <tbody>
                {паритет.kinds.map((k) => (
                  <tr key={k.kind} className="border-t border-border/30">
                    <td className="px-3 py-1.5">{k.title}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{k.onec || '—'}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{k.onec_period || '—'}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{когда(k.onec_last)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{k.ledger || '—'}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{k.ledger_period || '—'}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{когда(k.ledger_last)}</td>
                    <td className="px-3 py-1.5">
                      {k.own
                        ? <span className="text-muted-foreground">наш собственный</span>
                        : k.covered
                          ? <span className={k.used ? 'text-emerald-400/90' : 'text-muted-foreground'}>
                              {k.used ? 'умеем и делаем' : 'умеем, ещё не заводили'}
                            </span>
                          : <span className="text-amber-300/90">не умеем</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
