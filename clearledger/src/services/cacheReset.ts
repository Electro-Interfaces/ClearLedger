/**
 * Агрегатор сброса/синхронизации модульных кэшей сервисов при смене компании.
 * Вызывается из CompanyContext (смена активной компании) и AuthContext (logout).
 */
import * as sourceService from './sourceService'
import * as channelService from './channelService'
import * as locationService from './locationService'
import { clearAuthFileCache } from '@/lib/authFiles'

/** Полный сброс модульных кэшей (при смене компании / выходе). */
export function resetServiceCaches() {
  sourceService.resetCache()
  channelService.resetCache()
  locationService.resetCache()
  clearAuthFileCache()
}

/** Прокинуть активную компанию в сервисы (ключи localStorage / _companyId). */
export function setServicesCompany(id: string) {
  sourceService.setActiveCompany(id)
  channelService.setActiveCompany(id)
  locationService.setActiveCompany(id)
}
