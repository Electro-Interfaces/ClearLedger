/**
 * Заглушка раздела, экран которого ещё не собран: назначение и волна плана.
 * Пункт меню не прячем — человек видит, что здесь будет и когда.
 */
import { Construction } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { voiceViewFor } from './views'
import { Heading } from './parts'

export default function VoiceStubPage() {
  const v = voiceViewFor(useLocation().pathname)
  const когда = v.wave ? `Экран войдёт в волну ${v.wave} плана «Телефонии».`
    : 'Это ступень 2: АТС компании. Экран появится, когда узел начнёт обслуживать внутренние номера.'
  return (
    <div className="space-y-4 p-4">
      <Heading имя={v.label} />
      <EmptyBlock иконка={Construction} текст={`Здесь будет: ${v.hint}`} подсказка={когда} />
    </div>
  )
}
