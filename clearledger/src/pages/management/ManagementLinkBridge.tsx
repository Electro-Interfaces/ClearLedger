import { useEffect, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Building2, Loader2 } from 'lucide-react'
import { useCompany } from '@/contexts/CompanyContext'
import { useAuth } from '@/contexts/AuthContext'
import { useSupportContext } from '@/contexts/SupportContext'
import { EmptyState } from '@/components/common/EmptyState'

const UUID = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i

/** Deep link выбирает только membership из /me, до монтирования экрана оригинала. */
export function ManagementLinkBridge({ children }: { children: ReactNode }) {
  const { companyId, companies, setCompanyId } = useCompany()
  const { user, loading } = useAuth()
  const { openInteraction, setInteractionMode } = useSupportContext()
  const location = useLocation()
  const navigate = useNavigate()
  const params = new URLSearchParams(location.search)
  const requestedCompany = params.get('company')
  const chat = params.get('chat')
  const membershipReady = !loading && !!user && (companies.length === 0 || !!companyId)
  const allowed = !requestedCompany || companies.some((company) => company.id === requestedCompany)
  const switching = !!requestedCompany && companyId !== requestedCompany

  useEffect(() => {
    if (!membershipReady || !allowed) return
    if (switching) { setCompanyId(requestedCompany!); return }
    if (!requestedCompany && !chat) return
    if (chat && UUID.test(chat)) {
      openInteraction('chat', `room:${chat}`)
      // Стол / имеет только InteractionModal, бокового дока у него нет.
      if (location.pathname === '/') setInteractionMode('modal')
    }
    const next = new URLSearchParams(location.search)
    next.delete('company')
    next.delete('chat')
    navigate({ pathname: location.pathname, search: next.toString(), hash: location.hash }, { replace: true })
  }, [membershipReady, allowed, switching, requestedCompany, chat, setCompanyId, openInteraction, setInteractionMode, navigate, location.pathname, location.search, location.hash])

  if ((requestedCompany || chat) && !membershipReady) return <div role="status" className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Проверяем организацию…</div>
  if (requestedCompany && !allowed) return <EmptyState icon={Building2} title="Организация недоступна"
    description="Ссылка ведёт в организацию, к которой у вас нет доступа."
    action={{ label: 'К текущему пространству', onClick: () => navigate('/', { replace: true }) }} />
  if (switching) return <div role="status" className="p-6 text-sm text-muted-foreground">Открываем организацию…</div>
  return children
}
