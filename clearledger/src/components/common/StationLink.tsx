/**
 * Номер станции, по которому можно перейти на саму станцию.
 *
 * Ставится везде, где в форме, отчёте или на карте показан номер или название
 * ЭЗС. Клик открывает карточку объекта поверх экрана; закрытие возвращает туда
 * же, откуда пришли (см. `StationCardContext`).
 *
 * Станции нет в реестре — ссылки нет, остаётся обычный текст. Ложная ссылка
 * хуже её отсутствия: нажав раз в пустоту, человек перестаёт верить остальным.
 * По той же причине текст показывается и пока реестр грузится: подчёркивание
 * появляется, когда за ним уже есть станция.
 */
import { useEffect } from 'react'
import { cn } from '@/lib/utils'
import { useStationCard } from '@/contexts/StationCardContext'

export function StationLink({
  station, children, className, title,
}: {
  /** Код, номер, идентификатор или название станции — как она названа в форме. */
  station: string | null | undefined
  /** Что показать. По умолчанию — само значение. */
  children?: React.ReactNode
  className?: string
  title?: string
}) {
  const карточка = useStationCard()
  const { нужен } = карточка
  // Реестр объектов весит под два мегабайта и грузится не всегда, а когда на
  // экране появились ссылки на станции.
  useEffect(() => { нужен() }, [нужен])

  const объект = карточка.find(station)
  const текст = children ?? station ?? '—'

  if (!объект) return <>{текст}</>

  return (
    <button
      type="button"
      onClick={(e) => {
        // Строка таблицы часто сама по себе кликабельна (разворот, выделение):
        // переход на станцию не должен попутно делать её работу.
        e.stopPropagation()
        карточка.open(station)
      }}
      title={title ?? `${объект.name} — открыть карточку станции`}
      className={cn(
        'inline text-left underline decoration-dotted underline-offset-2',
        'hover:text-primary hover:decoration-solid focus-visible:outline-none',
        'focus-visible:ring-2 focus-visible:ring-ring rounded-sm',
        className,
      )}
    >
      {текст}
    </button>
  )
}
