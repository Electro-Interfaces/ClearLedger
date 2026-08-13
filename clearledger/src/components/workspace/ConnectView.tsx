/**
 * «Подключения» — панель раздела рабочей области: пункты во второй колонке, экран
 * равен выбранному пункту.
 *
 * Приложение было собрано из шести отдельных страниц (`paths` без секции в рельсе),
 * и левое меню показывало их плоским списком — как будто каждая страница отдельный
 * раздел. При этом маршрут `/connect`, на который ведут плитка стола и лаунчер, вёл
 * в рабочую область без единого раздела: секции `connect` не существовало.
 *
 * Пути страниц остаются рабочими — на них ведут глубокие ссылки из витрины и
 * каталога, — но входят люди сюда.
 */
import { ScrollArea } from '@/components/ui/scroll-area'
import { CentralPanelLayout } from './CentralPanelLayout'
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
  // Пункт живёт в адресе (`?sub=`), как во всех продуктах пространства: у пункта есть
  // имя, ссылка и закладка, а «назад» возвращает к предыдущему пункту, а не выносит
  // из приложения.
  const [sub, setSub] = useWorkspaceSubView(items[0]?.key ?? 'connections',
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
    <CentralPanelLayout items={items} activeKey={sub} onSelect={setSub}>
      {/* Рабочая область раскладки — flex-1 overflow-hidden: без своей прокрутки
          длинные экраны («Каталог типов», «Приложения и модули») обрезались по низу
          окна и до конца списка было не долистать. */}
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
    </CentralPanelLayout>
  )
}
