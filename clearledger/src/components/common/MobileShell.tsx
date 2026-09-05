/**
 * Мобильные обвязки экрана: «потянуть — обновить» и плашка новой версии.
 *
 * Оба сюжета про одно: на телефоне вкладку не закрывают неделями. Данные стареют
 * молча, а выкаченные правки не доезжают до человека вовсе — он видит ту сборку,
 * что открыл когда-то, и справедливо считает, что ничего не изменилось.
 */
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, ArrowDown, RefreshCw, Smartphone } from 'lucide-react'
import { usePullToRefresh } from '@/hooks/usePullToRefresh'
import { APP_BUILD, APP_VERSION, applyUpdate, watchForUpdate } from '@/lib/appUpdate'
import {
  hasPwaInstallPrompt, isPwaInstalled, requestPwaInstall, subscribePwaInstall,
} from '@/lib/pwaInstall'
import { ECOSYSTEM_BRAND } from '@/config/brand'
import { cn } from '@/lib/utils'

/** Индикатор жеста: тянется вместе с экраном, а не появляется скачком. */
function PullHint({ state, distance }: { state: string; distance: number }) {
  if (state === 'idle' && distance === 0) return null
  return (
    <div className="pointer-events-none flex items-center justify-center overflow-hidden
                    text-[12px] text-muted-foreground transition-[height]"
      style={{ height: state === 'refreshing' ? 36 : distance }}>
      <span className="flex items-center gap-1.5">
        {state === 'refreshing' ? (
          <><Loader2 className="h-4 w-4 animate-spin" />Обновляем…</>
        ) : (
          <>
            <ArrowDown className={cn('h-4 w-4 transition-transform',
              state === 'ready' && 'rotate-180')} />
            {state === 'ready' ? 'Отпустите — обновим' : 'Потяните, чтобы обновить'}
          </>
        )}
      </span>
    </div>
  )
}

/**
 * Обёртка прокручиваемой области экрана: даёт жест обновления и следит за выкаткой.
 * Обновление — не перезагрузка страницы, а сброс кэша запросов: на телефоне
 * перезагрузка стоит секунд и теряет место в списке.
 */
export function MobileShell({ children, className }: {
  children: React.ReactNode
  className?: string
}) {
  const qc = useQueryClient()
  const { ref, state, distance } = usePullToRefresh(() => qc.refetchQueries())

  return (
    <div ref={ref} data-mobile-shell className={className}>
      <PullHint state={state} distance={distance} />
      {children}
    </div>
  )
}

/**
 * «Вышла новая версия». Не перезагружаем сами: человек может быть в середине
 * ввода, и молчаливая перезагрузка потеряет его текст. Показываем и ждём решения.
 */
export function UpdateBanner() {
  const [fresh, setFresh] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => watchForUpdate((r) => setFresh(r.version)), [])

  if (!fresh) return null
  return (
    // Над нижней навигацией телефона (h-14) и над безопасной зоной: иначе плашка
    // ложится на кнопки навигации, и «Обновить» нажимается через раз.
    <div className="fixed inset-x-2 bottom-[calc(env(safe-area-inset-bottom)+4.5rem)] z-40
                    flex items-center justify-between gap-2 rounded-lg border
                    border-primary/30 bg-primary/95 px-3 py-2 text-[13px]
                    text-primary-foreground shadow-lg backdrop-blur
                    md:inset-x-auto md:right-4 md:bottom-4 md:max-w-md">
      <span>
        Вышла новая версия{fresh !== APP_VERSION ? ` ${fresh}` : ''} — у вас {APP_VERSION}
      </span>
      <button
        className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md
                   bg-background px-3 font-medium text-foreground"
        disabled={busy}
        onClick={() => { setBusy(true); void applyUpdate() }}>
        <RefreshCw className={cn('h-4 w-4', busy && 'animate-spin')} />Обновить
      </button>
    </div>
  )
}

/** Версия сборки для подвала настроек: «на что жалуемся» начинается с неё. */
export function BuildStamp() {
  return (
    <span className="text-[11px] text-muted-foreground">
      Версия {APP_VERSION} · сборка {APP_BUILD}
    </span>
  )
}

/* ── Установка на телефон ──────────────────────────────────────────────────
 *
 * Платформы ведут себя по-разному, и надеяться на подсказку браузера нельзя:
 *
 * · Chrome/Edge/Samsung (Android, десктоп) — дают `beforeinstallprompt`, и только
 *   после него можно открыть системное окно установки. Событие приходит, лишь когда
 *   есть манифест с иконками 192/512 и активный service worker с обработчиком
 *   `fetch` — без любого из условий браузер молчит, ничего не сообщая.
 * · Safari (iOS/iPadOS) — события нет вовсе: ставится только руками через
 *   «Поделиться» → «На экран «Домой»». Значит нужна не кнопка, а инструкция.
 * · Firefox Android — свой пункт меню, отдельного события тоже нет.
 *
 * Поэтому здесь два пути и ни одного молчаливого: где можно — кнопка, где нельзя —
 * шаги для этой платформы. Человек, которому «ничего не предложили», видит, что делать.
 */
const isIos = () =>
  /iphone|ipad|ipod/i.test(navigator.userAgent)
  // iPadOS 13+ представляется Mac: отличаем по наличию тач-ввода.
  || (/mac/i.test(navigator.userAgent) && navigator.maxTouchPoints > 1)

const isAndroid = () => /android/i.test(navigator.userAgent)

const DISMISS_KEY = 'cl-install-dismissed-at:v3'
const DISMISS_FOR_MS = 24 * 60 * 60 * 1000

function wasRecentlyDismissed(): boolean {
  try {
    const dismissedAt = Number(localStorage.getItem(DISMISS_KEY))
    return Number.isFinite(dismissedAt) && dismissedAt > 0
      && Date.now() - dismissedAt < DISMISS_FOR_MS
  } catch {
    return false
  }
}

export function InstallApp() {
  const bannerRef = useRef<HTMLDivElement>(null)
  const [promptAvailable, setPromptAvailable] = useState(hasPwaInstallPrompt)
  const [hidden, setHidden] = useState(wasRecentlyDismissed)
  const [installed, setInstalled] = useState(isPwaInstalled)
  const [howto, setHowto] = useState(false)

  useEffect(() => {
    try { localStorage.removeItem('cl-install-skipped') } catch { /* storage недоступен */ }
    return subscribePwaInstall((next) => {
      setInstalled(next.installed)
      setPromptAvailable(next.promptAvailable)
    })
  }, [])

  const visible = !installed && !hidden
  useEffect(() => {
    if (!visible || !bannerRef.current) return
    const update = () => document.documentElement.style.setProperty('--pwa-install-height', `${bannerRef.current?.offsetHeight ?? 0}px`)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(bannerRef.current)
    return () => { observer.disconnect(); document.documentElement.style.removeProperty('--pwa-install-height') }
  }, [visible])
  useEffect(() => {
    if (visible) document.documentElement.dataset.pwaInstall = howto ? 'expanded' : 'compact'
    else delete document.documentElement.dataset.pwaInstall
    return () => { delete document.documentElement.dataset.pwaInstall }
  }, [visible, howto])

  // Уже открыто приложением — предлагать нечего: это не спрятанный по условию
  // элемент, а завершённое действие. «Позже» скрывает плашку на сутки, но не навсегда.
  // Не прячем установку за авторизацией: системное событие может прийти уже на
  // экране входа, и это нормальная точка установки, как в Monitor TradeFrame.
  if (!visible) return null

  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())) } catch { /* storage недоступен */ }
    setHidden(true)
  }

  const install = async () => {
    const outcome = await requestPwaInstall()
    if (outcome === 'dismissed') dismiss()
  }

  return (
    <div ref={bannerRef} data-pwa-install className="fixed inset-x-2 bottom-[calc(env(safe-area-inset-bottom)+4.5rem)] z-40
                    rounded-lg border border-border bg-card/95 px-3 py-2 text-[13px]
                    shadow-lg backdrop-blur
                    md:inset-x-auto md:right-4 md:bottom-4 md:max-w-md">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <Smartphone className="h-4 w-4 shrink-0" />
          Держать {ECOSYSTEM_BRAND} под рукой — поставьте приложением
        </span>
        {promptAvailable ? (
          <button
            className="min-h-11 rounded-md bg-primary px-3 text-[13px] font-medium
                       text-primary-foreground"
            onClick={() => { void install() }}>
            Установить
          </button>
        ) : (
          <button className="min-h-11 text-[13px] text-primary hover:underline"
            onClick={() => setHowto((v) => !v)}>
            {howto ? 'Свернуть' : 'Как поставить'}
          </button>
        )}
        <button className="min-h-11 px-2 text-[13px] text-muted-foreground hover:underline"
          onClick={dismiss}>
          Позже
        </button>
      </div>

      {howto && !promptAvailable && (
        <div className="mt-2 border-t border-border/60 pt-2 text-[12px] leading-relaxed
                        text-muted-foreground">
          {isIos() ? (
            <>Safari: кнопка <b>«Поделиться»</b> внизу экрана → <b>«На экран «Домой»»</b> →
              «Добавить». Приложение встанет иконкой рядом с остальными.</>
          ) : isAndroid() ? (
            <>Для полноценного приложения без значка браузера откройте сайт в Google Chrome
              и используйте только <b>«Установить приложение»</b>. Пункт <b>«Добавить на
              главный экран»</b> создаёт обычный ярлык сайта.</>
          ) : (
            <>Для отдельного приложения используйте пункт браузера <b>«Установить
              приложение»</b>. Если его нет, откройте сайт в Chrome или Edge.</>
          )}
        </div>
      )}
    </div>
  )
}
