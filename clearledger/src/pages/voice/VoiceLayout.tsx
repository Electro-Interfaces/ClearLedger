/**
 * Оболочка приложения «Телефония» — администратор узла заказчика.
 *
 * Канон пространства: разделы в левой рельсе, заголовок экрана равен имени
 * пункта — та же геометрия, что у «Конференций» и «Трека». Меню сгруппировано по
 * частоте (работа, настройка, подключения, контроль), группа «АТС компании»
 * стоит неактивной: место под ступень 2 занято уже сейчас.
 *
 * Перед разделами оболочка спрашивает у узла `/me`: пускает ли он этого человека.
 * Отказ узла объясняется здесь, один раз, а не в каждом разделе отдельно.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen, PhoneOff } from 'lucide-react'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { VOICE_GROUPS, VOICE_VIEWS, voicePath, voiceViewFor } from './views'

/** Меньше этой ширины меню разделов (240 px) оставило бы экрану меньше 480 px. */
const ТЕСНО = 720

export function VoiceLayout() {
  const { companyId } = useCompany()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const узкий = useMaxWidth(768)
  const [свёрнута, setСвёрнута] = useState(() => {
    try { return localStorage.getItem('voice-rail') === 'closed' } catch { return false }
  })
  useEffect(() => {
    try { localStorage.setItem('voice-rail', свёрнута ? 'closed' : 'open') } catch { /* приватный режим */ }
  }, [свёрнута])

  // Сколько места у «Телефонии» на самом деле, а не у окна: при открытой боковой панели пространства
  // на 800 px экрану оставалось около 250 px, и формы уезжали за край. В тесноте меню разделов
  // свёрнуто и раскрывается поверх экрана, не сжимая его.
  const корень = useRef<HTMLDivElement>(null)
  const [ширина, setШирина] = useState(0)
  const [поверх, setПоверх] = useState(false)
  useEffect(() => {
    const el = корень.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width)
      setШирина(w)
      if (w >= ТЕСНО) setПоверх(false)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [узкий])
  const тесно = ширина > 0 && ширина < ТЕСНО

  const кто = useQuery({
    queryKey: ['voice-me', companyId],
    queryFn: () => voice.me(companyId),
    enabled: !!companyId,
    retry: 1,
    staleTime: 5 * 60_000,
  })

  const активный = voiceViewFor(pathname)

  // Ключ по компании: другой узел — экраны начинают с чистого листа, без чужой правки и выбранного звонка.
  const содержимое = кто.isError ? <Refusal ошибка={кто.error} /> : <Outlet key={companyId} />

  if (узкий) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <nav aria-label="Разделы Телефонии" className="shrink-0 border-b border-border bg-card p-2">
          <select aria-label="Раздел Телефонии" value={voicePath(активный)}
            onChange={e => navigate(e.target.value)}
            className="min-h-11 w-full rounded-md border border-input bg-background px-3 text-base">
            {VOICE_GROUPS.map(г => (
              <optgroup key={г.key} label={г.label}>
                {VOICE_VIEWS.filter(v => v.group === г.key).map(v => (
                  <option key={v.key} value={voicePath(v)}>{v.label}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto"
          style={{ paddingBottom: 'calc(var(--pwa-install-height, 0px) + 6rem + env(safe-area-inset-bottom))' }}>
          {содержимое}
        </div>
      </div>
    )
  }

  const открыть = () => (тесно ? setПоверх(true) : setСвёрнута(false))
  const закрыть = () => (тесно ? setПоверх(false) : setСвёрнута(true))

  const рельса = (
    <nav aria-label="Разделы Телефонии"
      className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-card px-1 py-3">
      <button type="button" onClick={открыть} aria-expanded={тесно ? поверх : undefined}
        title="Развернуть меню раздела" aria-label="Развернуть меню раздела"
        className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
        <PanelLeftOpen className="h-4 w-4" />
      </button>
    </nav>
  )

  const меню = (
    <nav aria-label={тесно ? 'Меню разделов Телефонии' : 'Разделы Телефонии'}
      onKeyDown={e => { if (тесно && e.key === 'Escape') setПоверх(false) }}
      className={cn('flex w-60 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border bg-card px-2.5 py-3',
        тесно && 'absolute inset-y-0 left-0 z-20 shadow-lg')}>
      <div className="flex items-center justify-end px-1 pb-1">
        <button type="button" onClick={закрыть}
          title="Свернуть меню" aria-label="Свернуть меню раздела"
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground">
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>
      {VOICE_GROUPS.map(г => (
        <div key={г.key} className="pb-2">
          <p className={cn('px-3 pb-1 pt-2 text-xs text-muted-foreground', г.key === 'pbx' && 'opacity-70')}>
            {г.label}
          </p>
          {VOICE_VIEWS.filter(v => v.group === г.key).map(v => (
            <button key={v.key} type="button" onClick={() => { navigate(voicePath(v)); setПоверх(false) }}
              title={v.hint} aria-current={v.key === активный.key ? 'page' : undefined}
              className={cn('flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors',
                v.key === активный.key
                  ? 'bg-primary/10 font-medium text-primary'
                  : г.key === 'pbx' ? 'text-muted-foreground hover:bg-accent/50' : 'text-foreground hover:bg-accent/50')}>
              <span className="min-w-0 flex-1 truncate">{v.label}</span>
            </button>
          ))}
        </div>
      ))}
    </nav>
  )

  return (
    <div ref={корень} className="relative flex h-full min-h-0">
      {тесно || свёрнута ? рельса : меню}
      {тесно && поверх && (
        <>
          <div aria-hidden="true" className="absolute inset-0 z-10 bg-background/40" onClick={() => setПоверх(false)} />
          {меню}
        </>
      )}
      <div className="min-w-0 flex-1 overflow-y-auto">
        {содержимое}
      </div>
    </div>
  )
}

/** Узел не пустил: словами, что случилось и кому это исправлять. */
function Refusal({ ошибка }: { ошибка: unknown }) {
  const недоступен = voice.узелНедоступен(ошибка)
  const текст = недоступен ? 'Узел заказчика не отвечает'
    : ошибка instanceof Error ? ошибка.message : 'Узел не пустил в «Телефонию»'
  const подсказка = недоступен
    ? 'Экраны «Телефонии» читают данные прямо из узла, через маршрут /voice стека. Проверьте, что узел запущен и маршрут до него открыт; звонки линии от этого не зависят.'
    : 'Пропуск в узел выдаёт Ядро пространства: токен «Телефонии» действует пять минут и обновляется сам. Если ошибка повторяется, проверьте роль администратора компании и адрес JWKS в настройках узла.'
  return (
    <div className="p-4">
      <EmptyBlock иконка={PhoneOff} текст={текст} подсказка={подсказка} />
    </div>
  )
}
