/**
 * Кэш короткоживущих пропусков к изолированному узлу.
 *
 * Модуль ничего не знает о браузере и HTTP: способ выдачи и часы приходят снаружи.
 */

export interface VoiceAccessToken {
  token: string
  exp: number
}

export interface VoiceAuthOptions {
  issue: (companyId: string) => Promise<VoiceAccessToken>
  now?: () => number
  refreshSkewMs?: number
}

export interface VoiceAuth {
  get: (companyId: string) => Promise<VoiceAccessToken>
  /** Без аргумента забывает все компании, с аргументом — только одну. */
  invalidate: (companyId?: string) => void
}

export function createVoiceAuth({
  issue,
  now = Date.now,
  refreshSkewMs = 60_000,
}: VoiceAuthOptions): VoiceAuth {
  const cache = new Map<string, VoiceAccessToken>()
  const inFlight = new Map<string, Promise<VoiceAccessToken>>()
  const companyGenerations = new Map<string, number>()
  let globalGeneration = 0

  function companyGeneration(companyId: string) {
    return companyGenerations.get(companyId) ?? 0
  }

  function invalidate(companyId?: string) {
    if (companyId == null) {
      globalGeneration++
      cache.clear()
      inFlight.clear()
      companyGenerations.clear()
      return
    }

    companyGenerations.set(companyId, companyGeneration(companyId) + 1)
    cache.delete(companyId)
    inFlight.delete(companyId)
  }

  async function get(companyId: string): Promise<VoiceAccessToken> {
    const cached = cache.get(companyId)
    if (cached && cached.exp - now() > refreshSkewMs) return cached

    const expectedGlobalGeneration = globalGeneration
    const expectedCompanyGeneration = companyGeneration(companyId)
    let request = inFlight.get(companyId)

    if (!request) {
      request = issue(companyId)
      inFlight.set(companyId, request)
      void request.finally(() => {
        if (inFlight.get(companyId) === request) inFlight.delete(companyId)
      }).catch(() => { /* исходная ошибка возвращается ожидающему get */ })
    }

    const issued = await request
    // Сброс мог произойти во время выдачи. Уже начатый вызов получает свой ответ,
    // но поздний пропуск прежней сессии не попадает в кэш новой.
    if (expectedGlobalGeneration !== globalGeneration
      || expectedCompanyGeneration !== companyGeneration(companyId)) {
      return issued
    }

    cache.set(companyId, issued)
    return issued
  }

  return { get, invalidate }
}
