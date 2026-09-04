/**
 * «Магазин» → Каталог → Матрица.
 *
 * Рабочее место товароведа сети. Позиция заводится один раз; всё, что
 * различается между станциями, описано правилами к ней, а не второй карточкой.
 * Правил десятки, карточек тысячи — поэтому экран показывает не «состояние
 * каждой ячейки», а исключения из умолчаний плюс ответ на вопрос «почему так»
 * для конкретной пары «станция × позиция».
 *
 * Два предмета, одна механика: право на цену и применение (возит ли станция
 * позицию). Умолчания разные и это осознанно — цена сетевая, пока право не
 * выдано явно; применение разрешено, пока не запрещено.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Grid3x3, Plus, X, HelpCircle, Lock } from 'lucide-react'
import {
  getStoreMatrix, addStoreMatrixRule, closeStoreMatrixRule, explainStoreMatrix,
  findNsiItems,
  type MatrixRule, type MatrixExplain,
} from '@/services/storeService'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'

type Предмет = 'price' | 'assortment'

const ИМЯ_ПРЕДМЕТА: Record<Предмет, string> = {
  price: 'Цена',
  assortment: 'Применение',
}

function когда(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru-RU',
    { day: '2-digit', month: '2-digit', year: '2-digit' })
}

/** Кого правило накрывает — словами, а не набором полей. */
function охват(п: MatrixRule, станции: { station_id: number; name: string }[]): string {
  const где = п.station_id === null
    ? 'вся сеть'
    : станции.find((s) => s.station_id === п.station_id)?.name ?? `АЗС ${п.station_id}`
  const что = п.item_id !== null
    // Артикул рядом с именем, а не вместо него: «позиция 100006643» не говорит
    // человеку ничего, а по имени он узнаёт товар с полки.
    ? `позиция «${п.item_name || 'без имени'}»${п.item_sku ? ` · ${п.item_sku}` : ''}`
    : п.group_path
      ? `группа «${п.group_path}»`
      : 'все позиции'
  return `${где} · ${что}`
}

export function StoreMatrixPanel() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const [предмет, задатьПредмет] = useState<Предмет>('price')
  const [формаОткрыта, открытьФорму] = useState(false)
  const [историю, показатьИсторию] = useState(false)

  // Поля формы нового правила.
  const [станция, задатьСтанцию] = useState<number | null>(null)
  const [группа, задатьГруппу] = useState<number | null>(null)
  const [поиск, задатьПоиск] = useState('')
  const [позиция, задатьПозицию] = useState<{ id: number; name: string } | null>(null)
  const [разрешить, задатьРазрешение] = useState(true)
  const [жёстко, задатьЖёсткость] = useState(false)
  const [причина, задатьПричину] = useState('')

  // Проверка «почему так».
  const [проверкаСтанция, задатьПроверкуСтанции] = useState<number | null>(null)
  const [проверкаПоиск, задатьПроверкуПоиска] = useState('')
  const [ответ, задатьОтвет] = useState<MatrixExplain | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['store-matrix', company.id, историю],
    queryFn: () => getStoreMatrix('', историю),
  })

  const кандидаты = useQuery({
    queryKey: ['matrix-item-search', поиск],
    queryFn: () => findNsiItems(поиск),
    enabled: поиск.trim().length >= 2,
  })

  // Ищем по ВЫБРАННОЙ станции, а не по зашитой в умолчании.
  //
  // findNsiItems подставляет 208, если станцию не передать: на АЗС 8 поиск шёл
  // по чужому справочнику, и позиции, которых на 208 нет, не находились вовсе —
  // выглядело это как «список не открывается».
  const проверочные = useQuery({
    queryKey: ['matrix-check-search', проверкаПоиск, проверкаСтанция],
    queryFn: () => findNsiItems(проверкаПоиск, проверкаСтанция ?? undefined),
    enabled: проверкаПоиск.trim().length >= 2 && проверкаСтанция !== null,
  })

  const завести = useMutation({
    mutationFn: addStoreMatrixRule,
    onSuccess: () => {
      toast.success('Правило заведено')
      открытьФорму(false)
      задатьПричину('')
      задатьПозицию(null)
      задатьПоиск('')
      qc.invalidateQueries({ queryKey: ['store-matrix'] })
    },
    onError: (e: Error) => toast.error('Правило не заведено', { description: e.message }),
  })

  const закрыть = useMutation({
    mutationFn: closeStoreMatrixRule,
    onSuccess: () => {
      toast.success('Правило закрыто; история осталась')
      qc.invalidateQueries({ queryKey: ['store-matrix'] })
    },
    onError: (e: Error) => toast.error('Не удалось закрыть правило', { description: e.message }),
  })

  const объяснить = useMutation({
    mutationFn: ({ st, item }: { st: number; item: number }) =>
      explainStoreMatrix(st, item, предмет),
    onSuccess: (r) => задатьОтвет(r),
    onError: (e: Error) => toast.error('Не удалось объяснить', { description: e.message }),
  })

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка матрицы…</div>
  if (error) return <div className="p-6 text-sm text-red-400/90">Не удалось получить матрицу</div>
  if (!data) return null

  const правила = data.rules.filter((п) => п.subject === предмет)
  // Сколько правил и какого охвата. Цифра отвечает на «только два состояния?»:
  // видно, что кроме «все позиции» бывают правила по группам и по отдельным
  // товарам, и сколько их сейчас.
  const правилаПоОхвату = {
    позиций: правила.filter((п) => !п.closed_at && п.item_id !== null).length,
    групп: правила.filter((п) => !п.closed_at && п.item_id === null && п.group_id !== null).length,
  }
  const умолчание = data.defaults[предмет]

  return (
    <div className="space-y-4 p-6">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <Grid3x3 className="h-4 w-4" /> Номенклатурная матрица
        </h3>
        <p className="text-xs text-muted-foreground">
          Позиция заводится один раз, различия между станциями описываются правилами к ней.
          Список ниже — исключения: всё, чего в нём нет, работает по умолчанию.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(['price', 'assortment'] as Предмет[]).map((s) => (
          <button
            key={s}
            onClick={() => { задатьПредмет(s); задатьОтвет(null) }}
            className={`rounded-md border px-3 py-1.5 text-xs ${
              предмет === s
                ? 'border-primary/60 bg-primary/10 font-medium'
                : 'border-border/50 text-muted-foreground hover:bg-muted/30'}`}
          >
            {ИМЯ_ПРЕДМЕТА[s]}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input type="checkbox" checked={историю}
                   onChange={(e) => показатьИсторию(e.target.checked)} />
            показать закрытые
          </label>
          <Button size="sm" variant="outline" onClick={() => открытьФорму((v) => !v)}>
            <Plus className="mr-1 h-3.5 w-3.5" /> Правило
          </Button>
        </div>
      </div>

      {/* Экран отвечает на два разных вопроса, и человек должен понимать, на
          каком он сейчас. «Цена» — кто вправе поставить цену. «Применение» —
          возит ли станция этот товар вообще. Пока вкладки были просто двумя
          словами, обе читались как «какие-то настройки». */}
      <div className="rounded-lg border border-border/50 bg-muted/20 p-3 text-xs space-y-1.5">
        <div>
          <b>{предмет === 'price' ? 'Цена' : 'Применение'}:</b>{' '}
          {предмет === 'price'
            ? 'кто ставит розничную цену — станция сама или центр. Запрет означает, что цена приезжает сетевая и на АЗС её не поменять.'
            : 'возит ли станция этот товар. Запрет означает, что позиция на АЗС не применяется: цена вниз не едет, в кассу товар не уходит — карточка есть, торговли нет.'}
        </div>
        <div><b>Умолчание компании:</b> {умолчание.text}</div>
        {/* Прямой ответ на «а если только часть позиций?» */}
        <div className="text-muted-foreground">
          Правило заводится на любой охват: вся сеть или одна АЗС, все позиции,
          товарная группа или одна позиция. Частное правило перебивает общее —
          позиция сильнее группы, группа сильнее «всех позиций».
          {' '}Сейчас правил: {(правила ?? []).filter((п) => !п.closed_at).length}
          {правилаПоОхвату.позиций > 0 && `, из них по отдельным позициям — ${правилаПоОхвату.позиций}`}
          {правилаПоОхвату.групп > 0 && `, по группам — ${правилаПоОхвату.групп}`}.
        </div>
      </div>

      {формаОткрыта && (
        <div className="space-y-3 rounded-lg border border-border/50 bg-card/40 p-4">
          <div className="text-sm font-medium">Новое правило: {ИМЯ_ПРЕДМЕТА[предмет].toLowerCase()}</div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">Станция</span>
              <select
                className="w-full rounded-md border border-border/50 bg-background px-2 py-1.5 text-xs"
                value={станция ?? ''}
                onChange={(e) => задатьСтанцию(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">вся сеть</option>
                {data.stations.map((s) => (
                  <option key={s.station_id} value={s.station_id}>
                    {s.name} {s.on_air ? '' : '(агента ещё нет)'}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-1 text-xs">
              <span className="text-muted-foreground">Группа (или оставьте пустой)</span>
              <select
                className="w-full rounded-md border border-border/50 bg-background px-2 py-1.5 text-xs"
                value={группа ?? ''}
                onChange={(e) => {
                  задатьГруппу(e.target.value ? Number(e.target.value) : null)
                  задатьПозицию(null)
                }}
                disabled={позиция !== null}
              >
                <option value="">все позиции</option>
                {data.groups.map((g) => (
                  <option key={g.group_id} value={g.group_id}>{g.path} ({g.items})</option>
                ))}
              </select>
            </label>
          </div>

          <label className="block space-y-1 text-xs">
            <span className="text-muted-foreground">
              Одна позиция (правило по карточке сильнее правила по группе)
            </span>
            <input
              className="w-full rounded-md border border-border/50 bg-background px-2 py-1.5 text-xs"
              placeholder="часть названия или штрихкод"
              value={позиция ? позиция.name : поиск}
              onChange={(e) => { задатьПоиск(e.target.value); задатьПозицию(null) }}
              disabled={группа !== null}
            />
          </label>
          {!позиция && (кандидаты.data?.items ?? []).length > 0 && (
            <div className="max-h-32 overflow-y-auto rounded-md border border-border/50">
              {(кандидаты.data?.items ?? []).slice(0, 12).map((it: { id: number; name: string }) => (
                <button
                  key={it.id}
                  onClick={() => { задатьПозицию({ id: it.id, name: it.name }); задатьПоиск('') }}
                  className="block w-full px-2 py-1 text-left text-xs hover:bg-muted/40"
                >
                  {it.name}
                </button>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-4 text-xs">
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={разрешить} onChange={() => задатьРазрешение(true)} />
              разрешить
            </label>
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={!разрешить} onChange={() => задатьРазрешение(false)} />
              запретить
            </label>
            {станция === null && !разрешить && (
              <label className="flex items-center gap-1.5 text-amber-400/90">
                <input type="checkbox" checked={жёстко}
                       onChange={(e) => задатьЖёсткость(e.target.checked)} />
                жёсткий запрет — станция не сможет перебить
              </label>
            )}
          </div>

          <label className="block space-y-1 text-xs">
            <span className="text-muted-foreground">
              Причина — обязательна: через полгода «почему так» спросят точно
            </span>
            <input
              className="w-full rounded-md border border-border/50 bg-background px-2 py-1.5 text-xs"
              placeholder="например: новая АЗС, цены ведёт администратор"
              value={причина}
              onChange={(e) => задатьПричину(e.target.value)}
            />
          </label>

          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={!причина.trim() || завести.isPending}
              onClick={() => завести.mutate({
                subject: предмет, allow: разрешить, reason: причина.trim(),
                station_id: станция, group_id: группа, item_id: позиция?.id ?? null,
                hard: жёстко && станция === null && !разрешить,
              })}
            >
              Завести
            </Button>
            <Button size="sm" variant="ghost" onClick={() => открытьФорму(false)}>Отмена</Button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Кого накрывает</th>
              <th className="px-3 py-2 text-left font-medium">Решение</th>
              <th className="px-3 py-2 text-left font-medium">Причина</th>
              <th className="px-3 py-2 text-left font-medium">Заведено</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {правила.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-muted-foreground">
                правил нет — всё работает по умолчанию
              </td></tr>
            )}
            {правила.map((п) => (
              <tr key={п.id} className={`border-t border-border/40 ${п.closed_at ? 'opacity-50' : ''}`}>
                <td className="px-3 py-2">{охват(п, data.stations)}</td>
                <td className="px-3 py-2">
                  <span className={п.allow ? 'text-emerald-400/90' : 'text-amber-400/90'}>
                    {п.allow ? 'разрешено' : 'запрещено'}
                  </span>
                  {п.hard && (
                    <span title="жёсткий запрет: станция не может перебить"
                          className="ml-1.5 inline-flex items-center text-red-400/90">
                      <Lock className="h-3 w-3" />
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-muted-foreground">{п.reason}</td>
                <td className="px-3 py-2 text-muted-foreground">{когда(п.created_at)}</td>
                <td className="px-3 py-2 text-right">
                  {!п.closed_at && (
                    <button
                      onClick={() => закрыть.mutate(п.id)}
                      title="закрыть правило (история останется)"
                      className="text-muted-foreground hover:text-red-400/90"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                  {п.closed_at && <span className="text-[10px]">закрыто {когда(п.closed_at)}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-3 rounded-lg border border-border/50 bg-card/40 p-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <HelpCircle className="h-4 w-4" /> Почему так
        </div>
        <p className="text-xs text-muted-foreground">
          Станция говорит «не могу поменять цену» — здесь видно, какое правило это решило
          и какие оно перебило.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <select
            className="rounded-md border border-border/50 bg-background px-2 py-1.5 text-xs"
            value={проверкаСтанция ?? ''}
            onChange={(e) => задатьПроверкуСтанции(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">выберите станцию</option>
            {data.stations.map((s) => (
              <option key={s.station_id} value={s.station_id}>{s.name}</option>
            ))}
          </select>
          <input
            className="rounded-md border border-border/50 bg-background px-2 py-1.5 text-xs"
            placeholder="позиция: часть названия или штрихкод"
            value={проверкаПоиск}
            onChange={(e) => задатьПроверкуПоиска(e.target.value)}
          />
        </div>
        {/* Подсказки состояния: пустое место без объяснения читается как поломка.
            Человек выбрал станцию, ввёл название — и не понимает, ждать ему или
            искать причину. */}
        {проверкаСтанция === null && (
          <p className="text-xs text-muted-foreground/70">Выберите станцию — поиск идёт по её справочнику.</p>
        )}
        {проверкаСтанция !== null && проверкаПоиск.trim().length > 0 && проверкаПоиск.trim().length < 2 && (
          <p className="text-xs text-muted-foreground/70">Введите хотя бы два знака.</p>
        )}
        {проверкаСтанция !== null && проверкаПоиск.trim().length >= 2 && проверочные.isLoading && (
          <p className="text-xs text-muted-foreground/70">Ищем…</p>
        )}
        {проверкаСтанция !== null && проверкаПоиск.trim().length >= 2
          && !проверочные.isLoading && (проверочные.data?.items ?? []).length === 0 && (
          <p className="text-xs text-muted-foreground/70">
            На этой станции ничего не нашлось. Позиция может быть заведена на другой АЗС.
          </p>
        )}
        {проверкаСтанция !== null && (проверочные.data?.items ?? []).length > 0 && (
          <div className="max-h-32 overflow-y-auto rounded-md border border-border/50">
            {(проверочные.data?.items ?? []).slice(0, 10).map((it: { id: number; name: string }) => (
              <button
                key={it.id}
                onClick={() => объяснить.mutate({ st: проверкаСтанция, item: it.id })}
                className="block w-full px-2 py-1 text-left text-xs hover:bg-muted/40"
              >
                {it.name}
              </button>
            ))}
          </div>
        )}
        {ответ && (
          <div className="space-y-1.5 rounded-md border border-border/50 bg-muted/20 p-3 text-xs">
            <div>
              <b className={ответ.allow ? 'text-emerald-400/90' : 'text-amber-400/90'}>
                {ответ.allow ? 'разрешено' : 'запрещено'}
              </b>
              {' — '}{ответ.explanation}
            </div>
            {ответ.overridden.length > 0 && (
              <div className="text-muted-foreground">
                перебиты правила: {ответ.overridden.map((п) => `${п.text} («${п.reason}»)`).join(' · ')}
              </div>
            )}
          </div>
        )}
      </div>

      <p className="text-xs text-muted-foreground/70">
        Правило не редактируется на месте: изменение — это новая запись, старая закрывается.
        История прав такой же документ, как история цен.
      </p>
    </div>
  )
}
