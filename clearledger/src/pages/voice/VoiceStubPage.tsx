/**
 * Раздел «Телефонии» по адресу, у которого нет своего маршрута в App.tsx: экраны волн 2.5 и 2.6
 * (каждый — отдельным куском сборки) или заглушка с назначением и волной плана.
 * Пункт меню не прячем — человек видит, что здесь будет и когда.
 */
import { lazy } from 'react'
import { Construction } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { voiceViewFor } from './views'
import { Heading } from './parts'

const ЭКРАНЫ: Record<string, React.LazyExoticComponent<() => React.JSX.Element>> = {
  sounds: lazy(() => import('./VoiceSoundsPage')),
  enrichment: lazy(() => import('./VoiceEnrichmentPage')),
  webhooks: lazy(() => import('./VoiceWebhooksPage')),
  audit: lazy(() => import('./VoiceAuditPage')),
  retention: lazy(() => import('./VoiceRetentionPage')),
  health: lazy(() => import('./VoiceHealthPage')),
  report: lazy(() => import('./VoiceReportPage')),
  reconcile: lazy(() => import('./VoiceReconcilePage')),
}

export default function VoiceStubPage() {
  const v = voiceViewFor(useLocation().pathname)
  const Экран = v.ready ? ЭКРАНЫ[v.key] : undefined
  if (Экран) return <Экран />
  const когда = v.wave ? `Экран войдёт в волну ${v.wave} плана «Телефонии».`
    : 'Это ступень 2: АТС компании. Экран появится, когда узел начнёт обслуживать внутренние номера.'
  return (
    <div className="space-y-4 p-4">
      <Heading имя={v.label} />
      <EmptyBlock иконка={Construction} текст={`Здесь будет: ${v.hint}`} подсказка={когда} />
    </div>
  )
}
