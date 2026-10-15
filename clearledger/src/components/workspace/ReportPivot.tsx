/**
 * Сводная отчёта сети — вторая подача таблицы, которую отчёт уже посчитал.
 *
 * Порт станционной сводной (`edge/agent/internal/web/report_pivot.go`): уровни
 * набираются чипами, порядок уровней = порядок нажатия, доля считается от
 * родителя, внизу «Итого». Приём один на все экраны — иначе у одного и того же
 * чипа заводится два разных поведения в центре и на АЗС.
 *
 * Считается на клиенте: строки отчёта уже в браузере, и гонять их на сервер
 * ради группировки незачем. Станция считает на сервере по обратной причине —
 * там данные и так в памяти процесса.
 *
 * ⚠ Измерения и меры узнаются по данным, а не по списку полей: имена колонок
 * задаёт сервер, и захардкоженный перечень разошёлся бы с ним при первом же
 * новом отчёте. Колонка числовая — мера, текстовая — измерение. Колонка, где
 * значения уникальны (товар, номер документа), измерением не становится:
 * группировка по ней даёт дерево из одиночных листьев, то есть тот же список.
 */
import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, GripVertical, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

type Строка = Record<string, unknown>

const nf = (n: number, d = 0) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(n)

/** Уровней больше четырёх дерево не читается — столько же на станции. */
const МАКСИМУМ = 4

type Узел = {
  имя: string
  уровень: number
  путь: string
  строк: number
  меры: number[]
  доля: number
  естьДети: boolean
}

/**
 * Разбор колонок: что можно взять разрезом, а что — мерой.
 *
 * Разрезом становится колонка, значения которой ПОВТОРЯЮТСЯ: группировка по
 * уникальной колонке (товар, номер документа) даёт дерево из одиночных
 * листьев — тот же список, только с отступами.
 *
 * Порог двойной, и это не перестраховка: доля 60 % отсекает почти-уникальные
 * колонки на больших таблицах, а «не больше 12 значений» пропускает короткий
 * словарь на маленьких. Без второго условия «Группа» с двумя значениями на трёх
 * строках (2 из 3 = 67 %) отсеивалась бы как уникальная.
 */
export function разрезыИМеры(fields: string[], columns: string[], rows: Строка[]) {
  const разрезы: { поле: string; имя: string }[] = []
  const меры: { поле: string; имя: string }[] = []
  // Почему колонка не стала разрезом — показывается под чипами. Без этого
  // человек видит три разреза при двадцати столбцах и не понимает, куда
  // делись остальные (МАГ, 15.10.2026).
  const мимо: { имя: string; почему: string }[] = []
  fields.forEach((поле, i) => {
    const имя = columns[i] ?? поле
    const непустые = rows.map((r) => r[поле]).filter((v) => v !== null && v !== undefined && v !== '')
    // Мера — по непустым: «Молчит, дн» заполнено только у молчащих станций, и
    // доля чисел от всех строк выкидывала колонку из мер.
    const числовых = непустые.filter((v) => typeof v === 'number').length
    if (числовых > 0 && числовых > непустые.length / 2) {
      меры.push({ поле, имя })
      return
    }
    if (непустые.length === 0) { мимо.push({ имя, почему: 'пусто' }); return }
    const уникальных = new Set(непустые.map(String)).size
    if (уникальных < 2) { мимо.push({ имя, почему: `у всех «${String(непустые[0])}»` }); return }
    if (уникальных >= непустые.length) { мимо.push({ имя, почему: 'у каждой строки своё' }); return }
    if (уникальных > 12 && уникальных > непустые.length * 0.6) {
      мимо.push({ имя, почему: `${уникальных} разных значений` }); return
    }
    разрезы.push({ поле, имя })
  })
  return { разрезы, меры, мимо }
}

function собрать(rows: Строка[], уровни: string[], меры: string[]): {
  узлы: Узел[]; итого: Узел
} {
  const пусто = (v: unknown) =>
    v === null || v === undefined || String(v).trim() === '' || String(v) === '—'
      ? 'без значения'
      : String(v)

  const сумма = (набор: Строка[]) =>
    меры.map((м) => набор.reduce((s, r) => s + (typeof r[м] === 'number' ? (r[м] as number) : 0), 0))

  const итого: Узел = {
    имя: 'Итого', уровень: 0, путь: '', строк: rows.length,
    меры: сумма(rows), доля: 1, естьДети: false,
  }

  const узлы: Узел[] = []
  const обойти = (набор: Строка[], глубина: number, путь: string, родитель: number) => {
    if (глубина >= уровни.length) return
    const поле = уровни[глубина]
    const группы = new Map<string, Строка[]>()
    for (const r of набор) {
      const ключ = пусто(r[поле])
      const было = группы.get(ключ)
      if (было) было.push(r)
      else группы.set(ключ, [r])
    }
    // Сортировка по главной мере — первой числовой: узел с наибольшими деньгами
    // должен стоять первым, ради этого сводную и открывают.
    const порядок = [...группы.entries()].sort((a, b) => {
      const [sa] = сумма(a[1])
      const [sb] = сумма(b[1])
      return (sb || 0) - (sa || 0)
    })
    for (const [имя, набор2] of порядок) {
      const меры2 = сумма(набор2)
      узлы.push({
        имя, уровень: глубина, путь: `${путь}/${имя}`, строк: набор2.length,
        меры: меры2,
        доля: родитель ? (меры2[0] || 0) / родитель : 0,
        естьДети: глубина + 1 < уровни.length,
      })
      обойти(набор2, глубина + 1, `${путь}/${имя}`, меры2[0] || 0)
    }
  }
  обойти(rows, 0, '', итого.меры[0] || 0)
  return { узлы, итого }
}

/** Перестановка уровня на одну позицию — та же, что в серверной сводной. */
function переставить(уровни: string[], из: number, в: number): string[] {
  if (в < 0 || в >= уровни.length) return уровни
  const следующие = уровни.slice()
  const [перенос] = следующие.splice(из, 1)
  следующие.splice(в, 0, перенос)
  return следующие
}

export function ReportPivot({ fields, columns, rows }: {
  fields: string[]
  columns: string[]
  rows: Строка[]
}) {
  const { разрезы, меры, мимо } = useMemo(
    () => разрезыИМеры(fields, columns, rows), [fields, columns, rows])
  // Первый разрез включён сразу: пустая сводная выглядит поломкой, а не
  // приглашением выбрать уровень.
  const [уровни, поставить] = useState<string[]>(() => разрезы.slice(0, 1).map((р) => р.поле))
  // Что тащим и над чем держим. Перетаскивание — основной способ менять порядок
  // уровней: стрелки остаются для клавиатуры и точной правки, но рукой человек
  // берёт чип и кладёт куда надо (требование МАГа, повторённое многократно).
  const [тащим, setТащим] = useState<number | null>(null)
  const [над, setНад] = useState<number | null>(null)
  const свободные = разрезы.filter((р) => !уровни.includes(р.поле))
  const мерыПоля = меры.map((м) => м.поле)

  // Ключ мер отдельной переменной: правило хуков требует в списке зависимостей
  // простые выражения, иначе проверку статически не сделать.
  const ключМер = мерыПоля.join(',')
  const { узлы, итого } = useMemo(
    () => собрать(rows, уровни, ключМер ? ключМер.split(',') : []),
    [rows, уровни, ключМер])

  // Свёрнутые группы. Помнятся, пока не поменялся набор уровней: при другой
  // группировке пути другие, и старые свёртки ничего не значат.
  const ключУровней = уровни.join('|')
  const [свёртка, setСвёртка] = useState<{ к: string; пути: Set<string> }>({ к: '', пути: new Set() })
  const свёрнуты = свёртка.к === ключУровней ? свёртка.пути : new Set<string>()
  const свернуть = (пути: Set<string>) => setСвёртка({ к: ключУровней, пути })
  const родители = узлы.filter((у) => у.естьДети)
  // «До уровня N»: открыты группы выше N-го уровня, остальные свёрнуты.
  const доУровня = (n: number) => свернуть(new Set(родители.filter((у) => у.уровень >= n - 1).map((у) => у.путь)))
  const глубина = (() => {
    for (let n = 1; n <= уровни.length; n++) {
      const надо = родители.filter((у) => у.уровень >= n - 1)
      if (надо.length === свёрнуты.size && надо.every((у) => свёрнуты.has(у.путь))) return n
    }
    return 0
  })()
  const видимые: Узел[] = []
  let скрытоПод: string | null = null
  for (const у of узлы) {
    if (скрытоПод !== null && у.путь.startsWith(скрытоПод + '/')) continue
    скрытоПод = свёрнуты.has(у.путь) ? у.путь : null
    видимые.push(у)
  }
  const переключить = (путь: string) => {
    const след = new Set(свёрнуты)
    if (след.has(путь)) след.delete(путь); else след.add(путь)
    свернуть(след)
  }

  if (разрезы.length === 0) {
    return (
      <div className="rounded-lg border border-border/50 px-3 py-6 text-center text-sm text-muted-foreground">
        Сводить нечего: в отчёте нет колонки, по которой можно сгруппировать строки.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
        <div className="text-[11px] text-muted-foreground">
          Группировка: нажмите разрез, чтобы добавить уровень; перетащите чип мышью
          или используйте стрелки, чтобы поменять порядок. До {МАКСИМУМ} уровней,
          итог каждой группы — в её строке.
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {уровни.length === 0 && (
            <span className="text-xs text-muted-foreground">
              ничего не выбрано — добавьте разрез
            </span>
          )}
          {/* Порядок уровней меняется на месте: пересобирать разрез снятием и
              добавлением ради перестановки двух уровней — работа на ровном месте. */}
          {уровни.map((поле, i) => (
            <span key={поле}
              draggable
              onDragStart={(e) => {
                setТащим(i)
                e.dataTransfer.effectAllowed = 'move'
                // Firefox не начинает перетаскивание без данных в буфере.
                e.dataTransfer.setData('text/plain', поле)
              }}
              onDragOver={(e) => { e.preventDefault(); setНад(i) }}
              onDragLeave={() => setНад((н) => (н === i ? null : н))}
              onDrop={(e) => {
                e.preventDefault()
                if (тащим !== null && тащим !== i) поставить(переставить(уровни, тащим, i))
                setТащим(null); setНад(null)
              }}
              onDragEnd={() => { setТащим(null); setНад(null) }}
              title="Перетащите, чтобы поменять порядок уровней"
              className={`inline-flex cursor-grab items-center gap-1 rounded border px-2 py-1 text-xs text-primary transition-colors active:cursor-grabbing ${
                над === i && тащим !== null && тащим !== i
                  ? 'border-primary bg-primary/25 ring-1 ring-primary'
                  : 'border-primary/40 bg-primary/10'
              } ${тащим === i ? 'opacity-50' : ''}`}>
              <GripVertical className="size-3 opacity-60" />
              <b>{i + 1}</b>
              {/* Имя — из колонок отчёта, а не из разрезов: после смены отбора
                  выбранный уровень может перестать быть разрезом (одно значение),
                  и чип показывал служебное имя поля — «reason» (14.10.2026). */}
              {columns[fields.indexOf(поле)] ?? поле}
              <button type="button" disabled={i === 0}
                onClick={() => поставить(переставить(уровни, i, i - 1))}
                aria-label="Переместить уровень выше" title="Выше"
                className="hover:text-foreground disabled:opacity-30">
                <ChevronLeft className="size-3" />
              </button>
              <button type="button" disabled={i === уровни.length - 1}
                onClick={() => поставить(переставить(уровни, i, i + 1))}
                aria-label="Переместить уровень ниже" title="Ниже"
                className="hover:text-foreground disabled:opacity-30">
                <ChevronRight className="size-3" />
              </button>
              <button type="button" onClick={() => поставить(уровни.filter((у) => у !== поле))}
                aria-label="Убрать уровень" title="Убрать"
                className="hover:text-destructive">
                <X className="size-3" />
              </button>
            </span>
          ))}
          {свободные.length > 0 && уровни.length < МАКСИМУМ && (
            <span className="ml-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">добавить уровень:</span>
              {свободные.map((р) => (
                <button key={р.поле} type="button"
                  onClick={() => поставить([...уровни, р.поле])}
                  className="rounded border border-border/60 px-2 py-1 text-xs text-muted-foreground hover:bg-accent/30">
                  + {р.имя}
                </button>
              ))}
            </span>
          )}
        </div>
        {/* Откуда список разрезов — вопрос МАГа 15.10.2026: разрез — любой
            столбец таблицы, где значения повторяются; числовые столбцы идут
            суммами в колонки. Остальное перечислено с причиной. */}
        <div className="mt-2 text-[11px] text-muted-foreground">
          Разрезы — столбцы таблицы с повторяющимися значениями, числа — суммами в колонках.{' '}
          {свободные.length === 0 && уровни.length > 0 && 'Все доступные разрезы уже в группировке. '}
          {мимо.length > 0 && <>Не разрезы: {мимо.map((м) => `«${м.имя}» — ${м.почему}`).join('; ')}.</>}
        </div>
        {родители.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Button variant="outline" size="sm" className="h-7 text-xs"
              disabled={свёрнуты.size === 0} onClick={() => свернуть(new Set())}>
              Развернуть все
            </Button>
            <Button variant="outline" size="sm" className="h-7 text-xs"
              disabled={глубина === 1} onClick={() => доУровня(1)}>
              Свернуть все
            </Button>
            {уровни.length > 1 && (
              <span role="group" aria-label="Раскрыть до уровня" className="ml-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                до уровня
                {уровни.map((поле, i) => (
                  <button key={поле} type="button" aria-pressed={глубина === i + 1}
                    title={`Раскрыть до уровня ${i + 1}: ${columns[fields.indexOf(поле)] ?? поле}`}
                    onClick={() => доУровня(i + 1)}
                    className={`size-7 rounded border text-xs ${глубина === i + 1
                      ? 'border-primary bg-primary/15 text-primary' : 'border-border/60 hover:bg-accent/30'}`}>
                    {i + 1}
                  </button>
                ))}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border/50">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Разрез</th>
              <th className="px-3 py-2 text-right font-medium">Строк</th>
              {меры.map((м) => (
                <th key={м.поле} className="whitespace-nowrap px-3 py-2 text-right font-medium">
                  {м.имя}
                </th>
              ))}
              <th className="px-3 py-2 text-right font-medium">Доля</th>
            </tr>
          </thead>
          <tbody>
            {/* Строка уровня — это и есть итог его группы: суммы мер по всем
                вложенным строкам. Пока она выглядела как лист, итоги читались
                как обычные значения, и «где суммарное по группе» спрашивали
                снова и снова (20.09.2026). Теперь узлы верхних уровней выделены
                фоном и насыщенностью — чем выше уровень, тем заметнее. */}
            {видимые.map((у) => (
              <tr key={у.путь}
                onClick={у.естьДети ? () => переключить(у.путь) : undefined}
                className={`border-t border-border/30 hover:bg-accent/20 ${у.естьДети ? 'cursor-pointer ' : ''}${
                  у.естьДети && у.уровень === 0 ? 'bg-muted/40 font-semibold'
                    : у.естьДети ? 'bg-muted/20 font-medium' : ''}`}>
                <td className="px-3 py-1.5" style={{ paddingLeft: 12 + у.уровень * 18 }}>
                  {у.естьДети && <ChevronRight className={`mr-1 inline size-3 text-muted-foreground transition-transform ${свёрнуты.has(у.путь) ? '' : 'rotate-90'}`} />}
                  {у.имя}
                  {у.естьДети && (
                    <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">
                      итог группы
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">{у.строк}</td>
                {у.меры.map((v, i) => (
                  <td key={i} className="px-3 py-1.5 text-right tabular-nums">
                    {nf(v, Number.isInteger(v) ? 0 : 2)}
                  </td>
                ))}
                <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                  {у.доля > 0 ? `${nf(у.доля * 100, 1)} %` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-border bg-muted/40 font-semibold">
              <td className="px-3 py-2">Итого</td>
              <td className="px-3 py-2 text-right tabular-nums">{итого.строк}</td>
              {итого.меры.map((v, i) => (
                <td key={i} className="px-3 py-2 text-right tabular-nums">
                  {nf(v, Number.isInteger(v) ? 0 : 2)}
                </td>
              ))}
              <td className="px-3 py-2 text-right">100 %</td>
            </tr>
          </tfoot>
        </table>
      </div>

      {уровни.length > 0 && узлы.length === 0 && (
        <Button variant="outline" size="sm" onClick={() => поставить([])}>
          Сбросить группировку
        </Button>
      )}
    </div>
  )
}
