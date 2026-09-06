import { get, put } from '@/services/apiClient'

export const HOME_SECTIONS = {
  work: 'На мне', chats: 'Чаты', meetings: 'Встречи', metrics: 'Показатели', apps: 'Приложения',
}
export type HomeSection = keyof typeof HOME_SECTIONS
export interface HomeConfig {
  sections: HomeSection[]
  favorite_apps: string[]
  metric_keys: string[] | null
}
export interface HomeSettings {
  effective: HomeConfig
  personal: HomeConfig | null
  default: HomeConfig
  personal_revision: number
  space_revision: number
  can_set_default: boolean
}
export const getHomeSettings = (companyId: string) =>
  get<HomeSettings>('/api/pulse/home-settings', { company_id: companyId })

export const saveHomeSettings = (companyId: string, scope: 'personal' | 'space',
  revision: number, config: HomeConfig | null) =>
  put<HomeSettings>(`/api/pulse/home-settings?company_id=${encodeURIComponent(companyId)}`,
    { scope, revision, config })
