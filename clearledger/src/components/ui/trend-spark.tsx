/**
 * Микро-график ряда: в строке таблицы или под цифрой плитки.
 *
 * Собран поверх `SparkLineChart` из чартовой базы. До него в проекте жили шесть
 * почти одинаковых `Sparkline` на голом `<polyline>`, и они успели разойтись:
 * где-то пропуски заменялись нулём (линия проваливалась к оси), где-то цвет
 * означал направление, где-то был нейтральный, а размеры задавались тремя
 * разными способами.
 *
 *   <TrendSpark values={row.values} />                     строка таблицы
 *   <TrendSpark values={k.spark} tone="muted" full />      под цифрой плитки
 */
import { SparkLineChart } from "@/components/ui/spark-chart"
import { cn } from "@/lib/utils"

export function TrendSpark({
  values,
  tone = "direction",
  full = false,
  className,
  placeholder = null,
}: {
  values: (number | null)[] | undefined
  /** direction — зелёный на росте, красный на падении; muted — нейтральный. */
  tone?: "direction" | "muted" | "brand"
  /** Растянуть на ширину контейнера (плитка) вместо фиксированной (таблица). */
  full?: boolean
  className?: string
  /** Что показать, когда ряда нет: в таблице — прочерк, в плитке — ничего. */
  placeholder?: React.ReactNode
}) {
  const vals = (values ?? []).filter((v): v is number => v != null)
  // Две точки — отрезок, а не тренд: рисовать нечего.
  if (vals.length < 2) return <>{placeholder}</>

  const rising = vals[vals.length - 1] >= vals[0]
  const color = tone === "direction" ? (rising ? "green" : "error")
    : tone === "brand" ? "brand" : "neutral"

  return (
    <SparkLineChart
      className={cn(full ? "h-7 w-full" : "inline-block h-4 w-16 align-middle", className)}
      data={(values ?? []).map((v, i) => ({ i, v }))}
      index="i"
      categories={["v"]}
      colors={[color]}
      // Пропуск соединяем, а не роняем в ноль: ноль в ряду цены читался бы как
      // продажа по нулю, а в ряду успеха — как полный провал.
      connectNulls
      autoMinValue
    />
  )
}
