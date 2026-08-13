/**
 * «Подключения» — панель раздела рабочей области: рисует экран выбранного пункта.
 *
 * Пункты раздела рисует ВТОРАЯ ПАНЕЛЬ рабочей области (`WorkspaceModeSidebar`) —
 * она берёт их из `workspaceSections`, как у всех продуктов пространства. Панель
 * своего меню не строит: когда она это делала (собственный `CentralPanelLayout`),
 * один и тот же список пунктов стоял на экране дважды, двумя колонками подряд.
 */
import { ScrollArea } from '@/components/ui/scroll-area'
import { useWorkspaceSections } from './workspaceSections'
import { useWorkspace, useWorkspaceSubView } from '@/contexts/WorkspaceContext'
import { ConnectionsPage, NotificationsPage, SpaceAppsPage } from '@/pages/ConnectPages'
import { CatalogPage } from '@/pages/CatalogPage'
import { SourcesPage } from '@/pages/SourcesPage'
import ChannelsPage from '@/pages/ChannelsPage'

export function ConnectView() {
  const { coreMode } = useWorkspace()
  const sections = useWorkspaceSections()
  const items = sections.find((s) => s.mode === coreMode)?.items ?? []
  // Выбранный пункт живёт в адресе (`?sub=`) — тот же ключ, которым его подсвечивает
  // вторая панель: меню и содержимое читают одно и то же место.
  const [sub] = useWorkspaceSubView(items[0]?.key ?? 'connections',
                                    items.map((i) => i.key))

  // Роль могла закрыть все пункты раздела: показываем это словами, а не пустотой.
  if (!items.length) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        В этом разделе нет доступных вам экранов. Права выдаются в «Управлении».
      </div>
    )
  }

  return (
    // Рабочая область — flex-1 overflow-hidden: без своей прокрутки длинные экраны
    // («Каталог типов», «Приложения и модули») обрезаются по низу окна.
    <ScrollArea className="h-full">
      <div className="p-4">
        {sub === 'connections' && <ConnectionsPage />}
        {sub === 'connectors' && <ChannelsPage />}
        {sub === 'sources' && <SourcesPage />}
        {sub === 'catalog' && <CatalogPage />}
        {sub === 'notifications' && <NotificationsPage />}
        {sub === 'apps' && <SpaceAppsPage />}
      </div>
    </ScrollArea>
  )
}
