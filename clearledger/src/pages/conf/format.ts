/**
 * Как «Конференции» показывают время, длительность и предмет конференции.
 *
 * Отдельным модулем, потому что этим пользуются все четыре раздела, а файл с
 * компонентами обязан экспортировать только компоненты.
 */
import { toast } from 'sonner'

/** «10 сентября, 14:30». Год печатается, только когда он не текущий. */
export function когда(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', {
    day: 'numeric', month: 'long',
    year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
    hour: '2-digit', minute: '2-digit',
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
