import { ArrowLeft } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { useNavigationHistory } from '@/contexts/navigationHistoryContextValue'
import { homePath } from '@/config/spaceProducts'
import { Button } from '@/components/ui/button'

export function NavigationBackButton() {
  const { history } = useNavigationHistory()
  const { company } = useCompany()
  const location = useLocation()
  const navigate = useNavigate()
  const home = homePath(company.profileId)
  const canGoBack = history.index > 0
  function goBack() {
    // Адрес меняется раньше, чем React завершит переход. В этот короткий
    // промежуток на экране ещё может быть шапка предыдущей страницы.
    const position = (window.history.state as { idx?: number } | null)?.idx
    const hasPrevious = position === undefined ? canGoBack : position > history.entries[0].position
    if (hasPrevious) navigate(-1)
    else navigate(home, { replace: true })
  }
  return (
    <Button type="button" variant="ghost" size="icon"
      className="size-11 shrink-0"
      aria-label="Назад" title={canGoBack ? 'На предыдущую страницу' : 'На рабочий стол'}
      disabled={!canGoBack && location.pathname === home && !location.search}
      onClick={goBack}>
      <ArrowLeft className="size-5" />
    </Button>
  )
}
