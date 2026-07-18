/**
 * Быстрая настройка: создание источника STS + канала «Загрузка сменных отчётов».
 * Для первоначальной инициализации без ручного прохождения всех шагов.
 */

import { getSources, createSource, updateSource } from './sourceService'
import { getChannels, createChannel, updateChannel } from './channelService'
import { saveSettings } from './settingsService'
import { stsLogin } from './fuel/stsApiClient'

export interface QuickSetupParams {
  login: string
  password: string
  systemCode?: number
  stationCode: number
  stationName?: string
}

export interface QuickSetupResult {
  sourceId: string
  channelId: string
  connected: boolean
  error?: string
}

/**
 * Создаёт источник STS API + канал «Загрузка сменных отчётов»
 * с конкретной станцией. Если источник STS уже есть — переиспользует.
 */
export async function quickSetup(params: QuickSetupParams): Promise<QuickSetupResult> {
  const systemCode = params.systemCode ?? 65

  // 1. Сохранить глобальные настройки
  saveSettings({
    stsLogin: params.login,
    stsPassword: params.password,
    stsSystemCode: systemCode,
    stations: [{ code: params.stationCode, name: params.stationName ?? `Станция ${params.stationCode}` }],
  })

  // 2. Найти или создать источник STS
  let source = getSources().find((s) => s.type === 'rest' && s.name.includes('STS'))
  if (!source) {
    source = await createSource({
      name: 'STS API ГИГ',
      type: 'rest',
      description: 'API системы управления АЗС (pos.autooplata.ru/tms)',
      connection: {
        url: 'https://pos.autooplata.ru/tms',
        login: params.login,
        password: params.password,
        systemCode: String(systemCode),
      },
    })
  } else {
    // Обновить credentials
    source = (await updateSource(source.id, {
      connection: {
        url: 'https://pos.autooplata.ru/tms',
        login: params.login,
        password: params.password,
        systemCode: String(systemCode),
      },
    }))!
  }

  // 3. Проверить подключение
  let connected = false
  let error: string | undefined
  try {
    await stsLogin(undefined, params.login, params.password)
    connected = true
    updateSource(source.id, { status: 'connected' })
  } catch (err) {
    error = err instanceof Error ? err.message : String(err)
    updateSource(source.id, { status: 'error', errorMessage: error })
  }

  // 4. Найти или создать канал
  let channel = getChannels().find((ch) => ch.name === 'Загрузка сменных отчётов')
  if (!channel) {
    channel = await createChannel({
      name: 'Загрузка сменных отчётов',
      sourceIds: [source.id],
      description: `Сменные отчёты с АЗС сети ГИГ (сеть ${systemCode})`,
      config: {
        stationCodes: [params.stationCode],
        systemCode,
      },
    })
  } else {
    // Обновить config
    updateChannel(channel.id, {
      config: {
        ...channel.config,
        stationCodes: [params.stationCode],
        systemCode,
      },
    })
  }

  return {
    sourceId: source.id,
    channelId: channel.id,
    connected,
    error,
  }
}
