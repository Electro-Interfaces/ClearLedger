/**
 * Тонкий роутер группы «Оборудование» раздела «Управленческий» (energy):
 * парк единиц · склады и остатки · журнал движений · ЗИП.
 * По образцу ChargeSalesRouter — правки панелей не задевают диспетчеризацию.
 */
import { EquipmentFleetPanel } from './EquipmentFleetPanel'
import { EquipmentWarehousesPanel } from './EquipmentWarehousesPanel'
import { EquipmentMovementsPanel } from './EquipmentMovementsPanel'
import { EquipmentSparesPanel } from './EquipmentSparesPanel'

export function EquipmentRouter({ tab, companyId }: { tab: string; companyId: string }) {
  switch (tab) {
    case 'eq_fleet':      return <EquipmentFleetPanel companyId={companyId} />
    case 'eq_warehouses': return <EquipmentWarehousesPanel companyId={companyId} />
    case 'eq_movements':  return <EquipmentMovementsPanel companyId={companyId} />
    case 'eq_spares':     return <EquipmentSparesPanel companyId={companyId} />
    default:              return null
  }
}
