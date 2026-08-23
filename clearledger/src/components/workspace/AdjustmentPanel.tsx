/**
 * Корректировки документов смены перед выгрузкой в 1С.
 *
 * Факт станции неприкосновенен: правка ложится поверх него отдельной записью и
 * помнит автора, причину и версию факта. Слева — что пришло со станции, справа —
 * что уйдёт в бухгалтерию; изменённое подсвечено, остальное выглядит обычно,
 * потому что обычным и является.
 *
 * Экран живёт в «Бухгалтерии»: в «Магазине» витрина факта, одинаковая со
 * станцией, и правки там быть не должно.
 */
import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getStoreShifts } from '@/services/storeService'
import { History, PencilLine, RotateCcw, TriangleAlert } from 'lucide-react'
import {
  getПредпросмотрПравок, getПравки, завестиПравку, отменитьПравку,
  измененияСтроки,
  type ДокСтрока, type ПараДокумента, type ЗаписьИстории,
} from '@/services/adjustmentService'
import { fmtMoney } from '@/services/analyticsService'
import { Button } from '@/components/ui/button'

/** Поля строки, которые бухгалтерия правит. Номенклатуру меняет станция документом. */
const ПОЛЯ: { ключ: keyof ДокСтрока; подпись: string; деньги?: boolean }[] = [
  { ключ: 'Количество', подпись: 'Кол-во' },
  { ключ: 'Цена', подпись: 'Цена', деньги: true },
  { ключ: 'Сумма', подпись: 'Сумма', деньги: true },
  { ключ: 'СуммаНДС', подпись: 'НДС', деньги: true },
]

const число = (v: unknown) => (typeof v === 'number' ? v : Number(v ?? 0))
const деньги = (v: unknown) => (число(v) === 0 ? '—' : fmtMoney(число(v)))
const кол = (v: unknown) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 }).format(число(v))

export function AdjustmentPanel({ companyId, dateFrom, dateTo }: {
  companyId: string; dateFrom: string; dateTo: string
}) {
  const [выбор, setВыбор] = useState<{ companyId: string; key: string } | null>(null)
  const ключ = выбор?.companyId === companyId ? выбор.key : null
  // companyId в ключе кеша обязателен: без него после смены компании панель
  // несколько минут показывает чужие смены.
  const смены = useQuery({
    queryKey: ['store-shifts', companyId, dateFrom, dateTo],
    queryFn: () => getStoreShifts(dateFrom, dateTo),
  })

  return (
    <div className="p-6 space-y-4">
      <div>
        <h3 className="text-base font-semibold">Корректировки перед выгрузкой</h3>
        <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
          Правка документа перед отправкой в 1С. Факт станции при этом не меняется: его видит
          администратор АЗС и раздел «Магазин», и он остаётся доказательством того, как продали.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(300px,380px)_1fr]">
        <div className="overflow-hidden rounded-lg border border-border/50">
          <div className="bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground">
            Смены {смены.data ? `(${смены.data.shifts.length})` : ''}
          </div>
          <div className="max-h-[520px] overflow-y-auto">
            {смены.isLoading && <div className="p-4 text-sm text-muted-foreground">Загрузка смен…</div>}
            {смены.error && <div className="p-4 text-sm text-destructive">Смены не загрузились</div>}
            <table className="w-full text-xs">
              <tbody>
                {смены.data?.shifts.map((см) => (
                  <tr
                    key={см.shift_key}
                    onClick={() => setВыбор({ companyId, key: см.shift_key })}
                    className={`cursor-pointer border-t border-border/30 ${
                      ключ === см.shift_key ? 'bg-accent/40' : 'hover:bg-accent/20'}`}
                  >
                    <td className="whitespace-nowrap px-3 py-1.5">{см.date}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">АЗС{см.station}</td>
                    <td className="px-3 py-1.5 text-right font-medium tabular-nums">
                      {деньги(см.revenue)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="min-w-0">
          <ДокументыСмены shiftKey={ключ ?? ''} />
        </div>
      </div>
    </div>
  )
}

function ДокументыСмены({ shiftKey }: { shiftKey: string }) {
  const qc = useQueryClient()
  const [правим, setПравим] = useState<{ док: ПараДокумента; строка: ДокСтрока } | null>(null)
  const [историю, setИсторию] = useState(false)

  const превью = useQuery({
    queryKey: ['adjustments', 'preview', shiftKey],
    queryFn: () => getПредпросмотрПравок(shiftKey),
    enabled: !!shiftKey,
  })
  const правки = useQuery({
    queryKey: ['adjustments', 'list', shiftKey],
    queryFn: () => getПравки(shiftKey),
    enabled: !!shiftKey,
  })

  const обновить = () => {
    qc.invalidateQueries({ queryKey: ['adjustments'] })
    qc.invalidateQueries({ queryKey: ['bp-package'] })
  }
  const отмена = useMutation({ mutationFn: отменитьПравку, onSuccess: обновить })

  const документы = превью.data?.Документы ?? []
  const устарели = превью.data?.Устарели ?? []

  if (!shiftKey) {
    return <Пусто текст="Выберите смену — корректировки относятся к её документам." />
  }
  if (превью.isLoading) return <Пусто текст="Собираем документы смены…" />
  if (превью.isError) {
    return <Пусто текст={`Документы смены не собрались: ${(превью.error as Error).message}`} />
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-3xl leading-relaxed">
          Слева — факт станции, он не меняется: те же цифры видит администратор АЗС и раздел
          «Магазин». Справа — то, что уйдёт в бухгалтерию. Правка ложится поверх факта и
          помнит, кто и почему её сделал.
        </p>
        <Button variant="outline" size="sm" onClick={() => setИсторию((v) => !v)}>
          <History className="h-3.5 w-3.5 mr-1.5" />
          История правок{правки.data?.история.length ? ` (${правки.data.история.length})` : ''}
        </Button>
      </div>

      {устарели.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-400/40 bg-amber-400/5 p-3 text-xs">
          <TriangleAlert className="h-4 w-4 shrink-0 text-amber-400 mt-0.5" />
          <div>
            <div className="font-medium text-amber-200">
              Смену пересчитали после этих правок — пакет не соберётся
            </div>
            <p className="text-muted-foreground mt-1">
              Правки сделаны на другой версии факта. Наложить их на новые цифры значит отправить
              в бухгалтерию число, которого никто не считал: пересмотрите или отмените.
            </p>
            <ul className="mt-2 space-y-1">
              {устарели.map((п) => (
                <li key={п.id} className="flex items-center gap-2">
                  <span className="text-foreground/80">{п.reason}</span>
                  <span className="text-muted-foreground">· {п.author}</span>
                  <button
                    onClick={() => отмена.mutate(п.id)}
                    className="text-amber-300 hover:text-amber-200 underline underline-offset-2"
                  >
                    отменить
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {историю && <ИсторияПравок записи={правки.data?.история ?? []} onОтмена={отмена.mutate} />}

      {документы.length === 0 && <Пусто текст="В смене нет документов для выгрузки." />}

      {документы.map((док) => (
        <Документ
          key={`${док.doc_kind}:${док.document_id}`}
          док={док}
          onПравить={(строка) => setПравим({ док, строка })}
        />
      ))}

      {правим && (
        <ФормаПравки
          док={правим.док}
          строка={правим.строка}
          shiftKey={shiftKey}
          onЗакрыть={() => setПравим(null)}
          onГотово={() => { setПравим(null); обновить() }}
        />
      )}
    </div>
  )
}

function Документ({ док, onПравить }: {
  док: ПараДокумента
  onПравить: (строка: ДокСтрока) => void
}) {
  const было = (док['От станции'].Товары ?? []) as ДокСтрока[]
  const стало = (док['К выгрузке'].Товары ?? []) as ДокСтрока[]
  const поНомеру = useMemo(
    () => new Map(стало.map((с) => [с.НомерСтроки, с])), [стало])

  return (
    <section className="rounded-lg border border-border/60 bg-card/40">
      <header className="flex items-center gap-2 px-3 py-2 border-b border-border/40">
        <span className="text-sm font-medium">
          {ИМЕНА_ВИДОВ[док.doc_kind] ?? док.doc_kind}
          {док.Номер ? ` № ${док.Номер}` : ''}
        </span>
        {док.Правился && (
          <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] text-primary">
            есть правки
          </span>
        )}
        <span className="ml-auto font-mono text-[10px] text-muted-foreground/60">
          {док.content_hash.slice(0, 10)}…
        </span>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr className="border-b border-border/40">
              <th className="px-3 py-2 text-left font-medium">Товар</th>
              {ПОЛЯ.map((п) => (
                <th key={String(п.ключ)} className="px-3 py-2 text-right font-medium">
                  {п.подпись}
                </th>
              ))}
              <th className="px-3 py-2 w-10" />
            </tr>
          </thead>
          <tbody>
            {было.map((строка) => {
              const правленая = поНомеру.get(строка.НомерСтроки) ?? строка
              const изменения = new Set(
                измененияСтроки(строка, правленая).map((и) => и.поле))
              return (
                <tr key={строка.НомерСтроки} className="border-b border-border/20 last:border-0">
                  <td className="px-3 py-1.5">
                    {строка.Наименование || `строка ${строка.НомерСтроки}`}
                  </td>
                  {ПОЛЯ.map((п) => {
                    const исходное = строка[п.ключ]
                    const новое = правленая[п.ключ]
                    const менялось = изменения.has(String(п.ключ))
                    const показ = (v: unknown) => (п.деньги ? деньги(v) : кол(v))
                    return (
                      <td key={String(п.ключ)} className="px-3 py-1.5 text-right tabular-nums">
                        {менялось ? (
                          <span className="inline-flex items-center gap-1.5">
                            <s className="text-muted-foreground/60">{показ(исходное)}</s>
                            <span className="font-medium text-primary">{показ(новое)}</span>
                          </span>
                        ) : (
                          показ(исходное)
                        )}
                      </td>
                    )
                  })}
                  <td className="px-2 py-1.5 text-right">
                    <button
                      onClick={() => onПравить(строка)}
                      title="Скорректировать строку"
                      className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
                    >
                      <PencilLine className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {док['К выгрузке'].Корректировка && (
        <div className="border-t border-border/40 px-3 py-2 text-[11px] text-muted-foreground space-y-1">
          {док['К выгрузке'].Корректировка!.Правки.map((п, i) => (
            <div key={i}>
              <span className="text-foreground/80">{п.Причина}</span>
              {' · '}{п.Автор}{' · '}{новая_дата(п.Когда)}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function ФормаПравки({ док, строка, shiftKey, onЗакрыть, onГотово }: {
  док: ПараДокумента
  строка: ДокСтрока
  shiftKey: string
  onЗакрыть: () => void
  onГотово: () => void
}) {
  const [значения, setЗначения] = useState<Record<string, string>>(() =>
    Object.fromEntries(ПОЛЯ.map((п) => [String(п.ключ), String(строка[п.ключ] ?? '')])))
  const [причина, setПричина] = useState('')
  const [ошибка, setОшибка] = useState('')

  const сохранить = useMutation({
    mutationFn: завестиПравку,
    onSuccess: onГотово,
    onError: (e: Error) => setОшибка(e.message),
  })

  const изменено = ПОЛЯ.filter((п) =>
    String(строка[п.ключ] ?? '') !== значения[String(п.ключ)])

  const отправить = () => {
    setОшибка('')
    if (!причина.trim()) {
      setОшибка('Без причины правка не сохраняется: через месяц никто не поймёт, почему цифра изменилась')
      return
    }
    if (изменено.length === 0) {
      setОшибка('Ничего не изменено')
      return
    }
    const правка: Record<string, unknown> = { НомерСтроки: строка.НомерСтроки }
    for (const п of изменено) {
      const сырое = значения[String(п.ключ)]
      const n = Number(сырое.replace(',', '.'))
      if (!Number.isFinite(n)) {
        setОшибка(`«${п.подпись}»: нужно число`)
        return
      }
      правка[String(п.ключ)] = n
    }
    сохранить.mutate({
      shift_key: shiftKey, doc_kind: док.doc_kind, document_id: док.document_id,
      base_content_hash: док.content_hash, patch: { Строки: [правка] },
      reason: причина.trim(),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-4 shadow-lg">
        <h3 className="text-sm font-semibold">
          Корректировка: {строка.Наименование || `строка ${строка.НомерСтроки}`}
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Факт станции останется прежним. Правка ляжет поверх него и уйдёт в бухгалтерию.
        </p>

        <div className="mt-3 grid grid-cols-2 gap-3">
          {ПОЛЯ.map((п) => (
            <label key={String(п.ключ)} className="text-xs">
              <span className="text-muted-foreground">{п.подпись}</span>
              <input
                value={значения[String(п.ключ)]}
                onChange={(e) => setЗначения((v) => ({ ...v, [String(п.ключ)]: e.target.value }))}
                inputMode="decimal"
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm tabular-nums focus:border-primary focus:outline-none"
              />
              <span className="mt-0.5 block text-[10px] text-muted-foreground/70">
                было {п.деньги ? деньги(строка[п.ключ]) : кол(строка[п.ключ])}
              </span>
            </label>
          ))}
        </div>

        <label className="mt-3 block text-xs">
          <span className="text-muted-foreground">Причина — обязательно</span>
          <input
            value={причина}
            onChange={(e) => setПричина(e.target.value)}
            placeholder="например: пересорт по накладной 208000000258"
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
          />
        </label>

        {ошибка && (
          <p className="mt-2 rounded-md border border-destructive/40 bg-destructive/5 px-2 py-1.5 text-xs text-destructive">
            {ошибка}
          </p>
        )}

        <div className="mt-4 flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onЗакрыть}>Отмена</Button>
          <Button size="sm" onClick={отправить} disabled={сохранить.isPending}>
            {сохранить.isPending ? 'Сохраняем…' : 'Сохранить правку'}
          </Button>
        </div>
      </div>
    </div>
  )
}

function ИсторияПравок({ записи, onОтмена }: {
  записи: ЗаписьИстории[]
  onОтмена: (id: string) => void
}) {
  if (записи.length === 0) {
    return <Пусто текст="Правок по этой смене не было." />
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border/60">
      <table className="w-full text-xs">
        <thead className="bg-muted/30 text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Когда</th>
            <th className="px-3 py-2 text-left font-medium">Документ</th>
            <th className="px-3 py-2 text-left font-medium">Что изменено</th>
            <th className="px-3 py-2 text-left font-medium">Причина</th>
            <th className="px-3 py-2 text-left font-medium">Кто</th>
            <th className="px-3 py-2 w-20" />
          </tr>
        </thead>
        <tbody>
          {записи.map((з) => {
            const отменена = з.status === 'cancelled'
            return (
              <tr key={з.id} className={`border-t border-border/30 ${отменена ? 'opacity-50' : ''}`}>
                <td className="px-3 py-1.5 whitespace-nowrap">{новая_дата(з.created_at)}</td>
                <td className="px-3 py-1.5">{ИМЕНА_ВИДОВ[з.doc_kind] ?? з.doc_kind}</td>
                <td className="px-3 py-1.5">
                  <span className={отменена ? 'line-through' : ''}>{краткоПравка(з.patch)}</span>
                </td>
                <td className="px-3 py-1.5 text-muted-foreground">{з.reason}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{з.author}</td>
                <td className="px-3 py-1.5 text-right">
                  {отменена ? (
                    <span className="text-[10px] text-muted-foreground">отменена</span>
                  ) : (
                    <button
                      onClick={() => onОтмена(з.id)}
                      className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
                    >
                      <RotateCcw className="h-3 w-3" /> отменить
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Пусто({ текст }: { текст: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
      {текст}
    </div>
  )
}

const ИМЕНА_ВИДОВ: Record<string, string> = {
  retail_sale_sidegoods: 'Отчёт о розничных продажах',
  purchase: 'Поступление',
  production_release: 'Выпуск',
  inventory: 'Инвентаризация',
  gain: 'Оприходование',
  writeoff: 'Списание',
  transfer: 'Перемещение',
  return_purchase: 'Возврат поставщику',
  recipe: 'Техкарта',
}

function краткоПравка(patch: ЗаписьИстории['patch']): string {
  const строки = patch?.Строки ?? []
  const шапка = patch?.Шапка ?? {}
  const части: string[] = []
  for (const с of строки) {
    const поля = Object.keys(с).filter((k) => k !== 'НомерСтроки')
    части.push(`строка ${с.НомерСтроки}: ${поля.map((k) => `${k} → ${с[k]}`).join(', ')}`)
  }
  for (const [k, v] of Object.entries(шапка)) части.push(`${k} → ${v}`)
  return части.join('; ') || '—'
}

function новая_дата(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
