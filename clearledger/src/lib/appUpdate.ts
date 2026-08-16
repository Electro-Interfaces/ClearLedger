/**
 * Версия сборки и жизнь вкладки после выкатки.
 *
 * Открытая вкладка ничего не знает о деплое: на телефоне «Пульс» живёт неделями,
 * и руководитель смотрит цифры вчерашней сборки, не подозревая об этом. Правок
 * интерфейса он тоже не увидит — и напишет, что «ничего не изменилось».
 *
 * Механика (тот же приём, что в ElsyPlus Monitor): при сборке рядом с ассетами
 * ложится `version.json`; приложение спрашивает его при возврате в окно и раз в
 * десять минут. Отличается метка — значит на сервере другая сборка.
 *
 * Сравниваем метку сборки, а не полагаемся на service worker: SW сообщает о себе
 * только когда сам обновился, а между его циклом и выкаткой фронта проходит время.
 */
export const APP_VERSION: string = __APP_VERSION__
export const APP_BUILD: string = __APP_BUILD__

const CHECK_EVERY = 10 * 60_000

type Listener = (remote: { version: string; build: string }) => void

async function fetchVersion(): Promise<{ version: string; build: string } | null> {
  try {
    // `no-store`, иначе браузер отдаст ту же копию, ради которой всё и затевалось.
    const r = await fetch(`${import.meta.env.BASE_URL}version.json`, { cache: 'no-store' })
    if (!r.ok) return null
    return await r.json()
  } catch {
    return null   // нет сети — не повод беспокоить человека
  }
}

/** Следить за выкаткой. Возвращает функцию отписки. */
export function watchForUpdate(onUpdate: Listener): () => void {
  let stopped = false

  const check = async () => {
    if (stopped || document.visibilityState === 'hidden') return
    const remote = await fetchVersion()
    if (!remote || stopped) return
    if (remote.build !== APP_BUILD) onUpdate(remote)
  }

  const onVisible = () => { if (document.visibilityState === 'visible') void check() }
  document.addEventListener('visibilitychange', onVisible)
  const timer = window.setInterval(() => void check(), CHECK_EVERY)
  void check()

  return () => {
    stopped = true
    document.removeEventListener('visibilitychange', onVisible)
    window.clearInterval(timer)
  }
}

/**
 * Забрать новую версию: сбросить кэш ассетов и перезагрузиться.
 *
 * Одного `location.reload()` мало, когда стоит service worker — он может отдать
 * старый ответ навигации; поэтому сначала просим его обновиться.
 */
export async function applyUpdate(): Promise<void> {
  try {
    if ('serviceWorker' in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations()
      await Promise.all(regs.map((r) => r.update()))
    }
  } catch {
    /* не смогли — перезагрузка всё равно полезна */
  }
  window.location.reload()
}
