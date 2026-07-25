/**
 * Центр управления → уровень ЭКОСИСТЕМА. Консоль администратора экосистемы:
 * Обзор · Карта · Каталог · Пользователи · Аудит · Оповещения · Настройки. Только суперадмин (Ур. 1).
 */
import { LayoutDashboard, Blocks, Users, History, Bell, Settings2, Map } from 'lucide-react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { SpaceMap } from '@/components/admin/SpaceMap'
import { usePersistentState } from '@/hooks/usePersistentState'
import { CoreOverview } from './CoreOverview'
import { EcosystemApps } from './EcosystemApps'
import { EcosystemUsers } from './EcosystemUsers'
import { EcosystemAudit } from './EcosystemAudit'
import { CoreAlerts } from './CoreAlerts'
import { CoreSettings } from './CoreSettings'

export function EcosystemConsole() {
  const [tab, setTab] = usePersistentState('cl-eco-tab', 'overview')
  return (
    <Tabs value={tab} onValueChange={setTab} className="w-full">
      <TabsList>
        <TabsTrigger value="overview" className="gap-1.5"><LayoutDashboard className="h-4 w-4" /> Обзор</TabsTrigger>
        {/* Карта: люди, доступы, активность и события одним экраном — для анализа,
            когда классические списки не дают увидеть картину целиком. */}
        <TabsTrigger value="map" className="gap-1.5"><Map className="h-4 w-4" /> Карта</TabsTrigger>
        <TabsTrigger value="catalog" className="gap-1.5"><Blocks className="h-4 w-4" /> Каталог</TabsTrigger>
        <TabsTrigger value="users" className="gap-1.5"><Users className="h-4 w-4" /> Пользователи</TabsTrigger>
        <TabsTrigger value="audit" className="gap-1.5"><History className="h-4 w-4" /> Аудит</TabsTrigger>
        <TabsTrigger value="alerts" className="gap-1.5"><Bell className="h-4 w-4" /> Оповещения</TabsTrigger>
        <TabsTrigger value="settings" className="gap-1.5"><Settings2 className="h-4 w-4" /> Настройки</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className="mt-4"><CoreOverview /></TabsContent>
      <TabsContent value="map" className="mt-4"><SpaceMap /></TabsContent>
      <TabsContent value="catalog" className="mt-4"><EcosystemApps /></TabsContent>
      <TabsContent value="users" className="mt-4"><EcosystemUsers /></TabsContent>
      <TabsContent value="audit" className="mt-4"><EcosystemAudit /></TabsContent>
      <TabsContent value="alerts" className="mt-4"><CoreAlerts /></TabsContent>
      <TabsContent value="settings" className="mt-4"><CoreSettings /></TabsContent>
    </Tabs>
  )
}
