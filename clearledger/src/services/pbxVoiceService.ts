/** Источники АТС разделены: журнал узла и история каждого провайдера. */
import * as api from './apiClient'
import type { MegafonCall, MegafonParams, MegafonVoiceData } from './megafonVoiceService'

export type CallSource = 'node' | 'mango' | 'megafon'
export const SOURCE_NAMES: Record<CallSource, string> = { node: 'Наш узел', mango: 'Mango', megafon: 'МегаФон' }
export type PbxVoiceData = Omit<MegafonVoiceData, 'provider' | 'connection'> & {
  provider: CallSource
  connection: Omit<MegafonVoiceData['connection'], 'mode'> & { mode: 'history' | 'events' }
}
export interface PbxSources {
  company_id: string
  default_source: CallSource
  sources: { source: CallSource; provider: 'asterisk' | 'mango' | 'megafon'; connector_id: string | null; enabled: boolean; status: string; last_sync_at: string | null; has_error: boolean }[]
}
export const isCallSource = (value: string | null): value is CallSource => value === 'node' || value === 'mango' || value === 'megafon'
function owned<T extends { company_id: string }>(data: T, companyId: string): T {
  if (!companyId || data.company_id !== companyId) throw new Error('Ответ относится к другой компании. Обновите страницу.')
  return data
}
export async function getPbxSources(companyId: string): Promise<PbxSources> {
  return owned(await api.get<PbxSources>('/api/voice/pbx/sources'), companyId)
}
export async function getPbxVoice(companyId: string, params: MegafonParams, source: CallSource): Promise<PbxVoiceData> {
  return owned(await api.get<PbxVoiceData>('/api/voice/pbx', { ...params, source }), companyId)
}
export async function getPbxCall(companyId: string, id: string, source: CallSource) {
  return owned(await api.get<{ call: MegafonCall; provider: CallSource; company_id: string }>(`/api/voice/pbx/calls/${encodeURIComponent(id)}`, { source }), companyId)
}
