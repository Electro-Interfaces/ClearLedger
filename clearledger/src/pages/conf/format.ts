/**
 * Как «Конференции» показывают время, длительность и предмет конференции.
 *
 * Отдельным модулем, потому что этим пользуются все четыре раздела, а файл с
 * компонентами обязан экспортировать только компоненты.
 */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { companyDateKey, COMPANY_TIME_ZONE } from '@/lib/companyTime'

/** «10 сентября, 14:30». Год печатается, только когда он не текущий. */
export function когда(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', {
    day: 'numeric', month: 'long',
    year: companyDateKey(d).slice(0, 4) === companyDateKey(new Date()).slice(0, 4) ? undefined : 'numeric',
    hour: '2-digit', minute: '2-digit',
    timeZone: COMPANY_TIME_ZONE,
  })
}

export function длительность(seconds?: number | null) {
  if (!seconds || seconds < 60) return seconds ? 'меньше минуты' : null
  const м = Math.round(seconds / 60)
  return м < 60 ? `${м} мин` : `${Math.floor(м / 60)} ч ${м % 60 ? `${м % 60} мин` : ''}`.trim()
}

/** Предмет конференции словами: `doc:<id>` человеку ничего не говорит. */
export function предмет(ref?: string | null) {
  if (!ref) return null
  const [вид, id] = ref.split(':')
  const имена: Record<string, string> = {
    doc: 'документ', task: 'поручение', ticket: 'заявка', project: 'проект',
  }
  const адреса: Record<string, string> = {
    doc: `/docs/card/${id}`, task: `/docs/work?task=${id}`, ticket: `/tickets?id=${id}`,
  }
  return { имя: имена[вид] ?? вид, адрес: адреса[вид] }
}

export function копировать(ссылка: string) {
  navigator.clipboard.writeText(ссылка)
    .then(() => toast.success('Ссылка для участников скопирована'))
    .catch(() => toast.error('Буфер обмена недоступен — скопируйте ссылку из карточки'))
}

export { СКОРО_МС, доНачала, скороНачало } from '@/lib/confTime'

/**
 * Текущее время, которое само идёт вперёд: отсчёт «через 12 мин» не должен
 * ждать, пока человек обновит страницу. Шаг — полминуты: минутная надпись не
 * отстаёт больше чем на полминуты, а таймеров на экране — по одному на строку.
 */
export function useСейчас(шагМс = 30_000) {
  const [сейчас, setСейчас] = useState(() => Date.now())
  useEffect(() => {
    const т = window.setInterval(() => setСейчас(Date.now()), шагМс)
    return () => window.clearInterval(т)
  }, [шагМс])
  return сейчас
}
