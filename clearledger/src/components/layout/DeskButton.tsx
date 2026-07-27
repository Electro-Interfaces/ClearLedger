/**
 * «Стол» — выход на рабочий стол пространства из любого продукта.
 *
 * Стоит в шапке перед «Приложениями»: сначала вернуться на стол, потом выбрать, куда
 * идти дальше — это один жест в одном месте. В правом рельсе кнопки больше нет: она
 * пряталась в нижней зоне, тогда как возврат нужен так же часто, как переключение
 * продукта, и жить им положено рядом.
 */
import { LayoutDashboard } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export function DeskButton() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  // На самом столе кнопка бессмысленна — там и так всё видно.
  if (pathname === '/') return null

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => navigate('/')}
      title="Рабочий стол пространства"
      // Вид общий с «Приложениями» и с кнопками пространства в других продуктах:
      // рамка без заливки, чтобы навигация не спорила с прикладными кнопками.
      className={
        'relative h-11 px-3 gap-2 rounded-xl border font-medium transition-colors duration-200 ' +
        'border-border bg-transparent text-foreground/80 hover:bg-accent hover:text-foreground'
      }
    >
      <LayoutDashboard className="h-4 w-4" />
      <span className="hidden lg:inline">Стол</span>
    </Button>
  )
}
