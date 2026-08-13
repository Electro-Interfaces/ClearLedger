/**
 * «Подключения» по канону рабочей области: раздел стоит в рельсе, его пункты — во
 * второй колонке, заголовок экрана равен имени пункта.
 *
 * Приложение было собрано из шести отдельных страниц (`paths` без `modes`), и рельса
 * показывала их плоским списком — как будто каждая страница отдельный раздел. Пути
 * остаются рабочими (на них ведут глубокие ссылки из каталога и карточек), но входят
 * люди сюда.
 */
import { useState } from 'react'
import { CentralPanelLayout, type CentralMenuItem } from './CentralPanelLayout'
import { ConnectionsPage, NotificationsPage, SpaceAppsPage } from '@/pages/ConnectPages'
import { CatalogPage } from '@/pages/CatalogPage'
import { SourcesPage } from '@/pages/SourcesPage'
import ChannelsPage from '@/pages/ChannelsPage'

const MENU: CentralMenuItem[] = [
  { key: 'state', label: 'Состояние' },
  { key: 'connectors', label: 'Коннекторы' },
  { key: 'sources', label: 'Источники' },
  { key: 'catalog', label: 'Каталог типов' },
  { key: 'notifications', label: 'Оповещения' },
  { key: 'apps', label: 'Приложения и модули' },
]

export function ConnectView() {
  const [tab, setTab] = useState('state')
  return (
    <CentralPanelLayout items={MENU} activeKey={tab} onSelect={setTab}>
      {tab === 'state' && <ConnectionsPage />}
      {tab === 'connectors' && <ChannelsPage />}
      {tab === 'sources' && <SourcesPage />}
      {tab === 'catalog' && <CatalogPage />}
      {tab === 'notifications' && <NotificationsPage />}
      {tab === 'apps' && <SpaceAppsPage />}
    </CentralPanelLayout>
  )
}
