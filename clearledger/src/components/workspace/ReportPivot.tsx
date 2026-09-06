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
import { ChevronRight, X } from 'lucide-react'
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
  fields.forEach((поле, i) => {
    const имя = columns[i] ?? поле
    const значения = rows.map((r) => r[поле])
    const числовых = значения.filter((v) => typeof v === 'number').length
    if (числовых > rows.length / 2) {
      меры.push({ поле, имя })
      return
    }
    const непустые = значения.filter((v) => v !== null && v !== undefined && v !== '')
    if (непустые.length === 0) return
    const уникальных = new Set(непустые.map(String)).size
    if (уникальных < 2 || уникальных >= непустые.length) return
    if (уникальных > 12 && уникальных > непустые.length * 0.6) return
    разрезы.push({ поле, имя })
  })
  return { разрезы, меры }
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

export function ReportPivot({ fields, columns, rows }: {
  fields: string[]
  columns: string[]
  rows: Строка[]
}) {
  const { разрезы, меры } = useMemo(
    () => разрезыИМеры(fields, columns, rows), [fields, columns, rows])
  // Первый разрез включён сразу: пустая сводная выглядит поломкой, а не
  // приглашением выбрать уровень.
  const [уровни, поставить] = useState<string[]>(() => разрезы.slice(0, 1).map((р) => р.поле))
  const свободные = разрезы.filter((р) => !уровни.includes(р.поле))
  const мерыПоля = меры.map((м) => м.поле)

  const { узлы, итого } = useMemo(
    () => собрать(rows, уровни, мерыПоля),
    [rows, уровни, мерыПоля.join(',')])

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
          Группировка — порядок уровней задаётся порядком нажатия, до {МАКСИМУМ} уровней
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {уровни.length === 0 && (
            <span className="text-xs text-muted-foreground">
              ничего не выбрано — добавьте разрез
            </span>
          )}
          {уровни.map((поле, i) => (
            <button key={поле} type="button"
              onClick={() => поставить(уровни.filter((у) => у !== поле))}
              className="inline-flex items-center gap-1 rounded border border-primary/40 bg-primary/10 px-2 py-1 text-xs text-primary">
              <b>{i + 1}</b>
              {разрезы.find((р) => р.поле === поле)?.имя ?? поле}
              <X className="size-3" />
            </button>
          ))}
          {свободные.length > 0 && уровни.length < МАКСИМУМ && (
            <span className="ml-2 flex flex-wrap gap-1.5">
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
            {узлы.map((у) => (
              <tr key={у.путь} className="border-t border-border/30 hover:bg-accent/20">
                <td className="px-3 py-1.5" style={{ paddingLeft: 12 + у.уровень * 18 }}>
                  {у.естьДети && <ChevronRight className="mr-1 inline size-3 text-muted-foreground" />}
                  {у.имя}
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
