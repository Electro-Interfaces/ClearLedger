/**
 * Сквозная сверка слоёв: факт станции → пакет → бухгалтерия.
 *
 * Найти разницу — полдела. Экран отвечает, чем она объясняется: правка
 * бухгалтера это решение человека, а «отправили одно, приняли другое» — поломка
 * канала, и разговор с 1С будет совсем другим.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CircleAlert, CircleCheck } from 'lucide-react'
import { getСверкаСлоёв, type СлойСверки } from '@/services/adjustmentService'
import { fmtMoney } from '@/services/analyticsService'

const СЛОИ: { ключ: 'Факт станции' | 'Отправлено' | 'В бухгалтерии'; метка: string; что: string }[] = [
  { ключ: 'Факт станции', метка: 'L2 · Факт станции', что: 'как продали и пробила касса' },
  { ключ: 'Отправлено', метка: 'L3 · Отправлено', что: 'что ушло в бухгалтерию' },
  { ключ: 'В бухгалтерии', метка: 'L4 · В бухгалтерии', что: 'что легло в БП' },
]

export function AdjustmentReconPanel({ shiftKey, companyId }: {
  shiftKey: string; companyId: string
}) {
  const сверка = useQuery({
    queryKey: ['adjustments', 'recon', companyId, shiftKey],
    queryFn: () => getСверкаСлоёв(shiftKey),
    enabled: !!shiftKey,
  })

  if (!shiftKey) {
    return <Пусто текст="Выберите смену — сверка идёт по её документам." />
  }
  if (сверка.isLoading) return <Пусто текст="Сверяем слои…" />
  if (сверка.isError) {
    return <Пусто текст={`Сверка не выполнилась: ${(сверка.error as Error).message}`} />
  }
  const д = сверка.data!

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
        Разницу между фактом станции и отправленным делают наши правки — она обязана сойтись
        с их суммой до копейки. Разницы между отправленным и тем, что легло в 1С, быть не должно
        вовсе: она означает, что приняли не то, что послали.
      </p>

      <div className="grid gap-3 sm:grid-cols-3">
        {СЛОИ.map((с, i) => (
          <div key={с.ключ} className="relative">
            <Слой метка={с.метка} что={с.что} данные={д.Слои[с.ключ]} />
            {i < СЛОИ.length - 1 && (
              <ArrowRight
                className="absolute -right-2.5 top-1/2 hidden h-4 w-4 -translate-y-1/2 text-muted-foreground/40 sm:block"
                aria-hidden="true"
              />
            )}
          </div>
        ))}
      </div>

      {д.Правок > 0 && (
        <p className="text-xs text-muted-foreground">
          Правок по смене: <span className="font-medium text-foreground">{д.Правок}</span>
          {' · '}их влияние{' '}
          <span className="font-medium tabular-nums text-foreground">
            {д.СуммаПравок > 0 ? '+' : ''}{fmtMoney(д.СуммаПравок)}
          </span>
        </p>
      )}

      <div className="space-y-2">
        {д.Выводы.map((в, i) => (
          <div
            key={i}
            className={`flex items-start gap-2.5 rounded-lg border p-3 text-xs ${
              в.ok
                ? 'border-border/60 bg-card/40'
                : 'border-amber-400/40 bg-amber-400/5'
            }`}
          >
            {в.ok
              ? <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              : <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />}
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-muted-foreground">{в.Слои}</span>
                <span className={`font-medium ${в.ok ? '' : 'text-amber-200'}`}>{в.Что}</span>
              </div>
              <p className="mt-0.5 text-muted-foreground">{в.Почему}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Слой({ метка, что, данные }: { метка: string; что: string; данные: СлойСверки }) {
  return (
    <div className={`h-full rounded-lg border p-3 ${
      данные.есть ? 'border-border/60 bg-card/40' : 'border-dashed border-border bg-muted/20'
    }`}>
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-medium text-muted-foreground">{метка}</span>
        {данные.источник && <ЗнакТочности источник={данные.источник} />}
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums">
        {данные.документов ? fmtMoney(данные.сумма) : '—'}
      </div>
      <div className="text-[11px] text-muted-foreground">
        {данные.документов ? `${данные.документов} док.` : 'нет данных'} · {что}
      </div>
      {данные.примечание && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground/80">
          {данные.примечание}
        </p>
      )}
    </div>
  )
}

/**
 * Насколько точно этот слой связан с 1С. Разница принципиальна: «наши» —
 * подокументно по UUID, «реестр» — вся станция за день, и сравнивать суммы в
 * лоб уже нельзя. Без этой пометки человек читает приблизительное как точное.
 */
function ЗнакТочности({ источник }: { источник: string }) {
  const вид: Record<string, { текст: string; стиль: string; подсказка: string }> = {
    'наши': {
      текст: 'по UUID', стиль: 'border-emerald-400/50 text-emerald-300/80',
      подсказка: 'наши документы найдены в 1С поимённо — по метке канала',
    },
    'канал ЦБ': {
      текст: 'канал ЦБ', стиль: 'border-blue-400/50 text-blue-300/80',
      подсказка: 'сопутка доставлена прежним каналом: документы собраны на день, не на смену',
    },
    'метка': {
      текст: 'по смене', стиль: 'border-amber-400/50 text-amber-300/80',
      подсказка: 'найдено по номеру смены в метке — это документы топливного канала',
    },
    'реестр': {
      текст: 'за день', стиль: 'border-zinc-600 text-zinc-400',
      подсказка: 'приблизительно: вся станция за день, включая соседние смены',
    },
  }
  const з = вид[источник]
  if (!з) return null
  return (
    <span title={з.подсказка}
      className={`rounded border px-1 py-px text-[9px] leading-none ${з.стиль}`}>
      {з.текст}
    </span>
  )
}

function Пусто({ текст }: { текст: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
      {текст}
    </div>
  )
}
