/**
 * Оболочка приложения «Телефония» — администратор узла заказчика.
 *
 * Разделы живут в левой рельсе пространства (`AppSidebar`, ветка `/voice`): группы
 * «Работа», «Настройка», «Подключения», «Контроль» сворачиваются тем же механизмом,
 * что «Данные» у Учёта. Своей колонки разделов у оболочки больше нет (решение МАГа
 * 17.10.2026): две рельсы подряд отнимали у экрана четверть ширины, а рабочая
 * область должна принадлежать разделу. До 1024 px рельсы на экране нет, и раздел
 * выбирается списком над экраном, как у «Конференций»; на телефоне те же группы
 * есть и в шторке «Модули».
 *
 * Перед разделами оболочка спрашивает у узла `/me`: пускает ли он этого человека.
 * Отказ узла объясняется здесь, один раз, а не в каждом разделе отдельно.
 */
import { lazy, Suspense } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { PhoneOff } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { useMaxWidth } from '@/hooks/use-mobile'
import { useCompany } from '@/contexts/CompanyContext'
import * as voice from '@/services/voiceService'
import { EmptyBlock } from '@/pages/conf/EmptyBlock'
import { VOICE_GROUPS, VOICE_VIEWS, voicePath, voiceViewFor } from './views'
import { useVoiceDataSource, VoiceDataSourceBar } from './VoiceDataSource'

const MegafonVoicePage = lazy(() => import('./PbxVoicePage'))
const MegafonMonthlyReportPage = lazy(() => import('./MegafonMonthlyReportPage'))

export function VoiceLayout() {
  const { companyId } = useCompany()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const connections = pathname.replace(/\/$/, '') === '/voice/connections'
  // Журнал АТС и историю провайдеров читает Ядро с проверкой компании, продукта и роли.
  const source = useVoiceDataSource(pathname)
  const history = source.providerHistory || source.directPbx
  // ≤1024 рельсы пространства на экране нет (MainLayout прячет её в шторку), поэтому раздел
  // выбирается списком сверху — как у «Конференций» на телефоне.
  const компакт = useMaxWidth(1024)
  const узкий = useMaxWidth(768)
  const кто = useQuery({
    queryKey: ['voice-me', companyId],
    queryFn: () => voice.me(companyId),
    enabled: !!companyId && !connections && !history && !source.loading && !source.error,
    // Повторяем только обрыв/временный 5xx. 403 role/company — окончательный ответ,
    // а 401 уже один раз обновляет токен в voiceService: других скрытых повторов нет.
    retry: (failureCount, error) => failureCount < 1 && voice.узелНедоступен(error),
    staleTime: 5 * 60_000,
  })

  // Ключ по компании: другой узел — экраны начинают с чистого листа, без чужой правки и выбранного звонка.
  const содержимое = connections ? <Outlet key={companyId} />
    : source.loading ? <AccessLoading />
    : source.error ? null
    : history ? (source.managed
      ? <Suspense fallback={<AccessLoading />}>{pathname.endsWith('/report')
        ? <MegafonMonthlyReportPage key={companyId} />
        : <MegafonVoicePage key={`${companyId}:${pathname}`} section={pathname.endsWith('/stats') ? 'stats' : 'calls'} />}</Suspense>
      : <Outlet key={companyId} />)
    : !companyId || кто.isLoading ? <AccessLoading />
    : кто.isError ? <Refusal ошибка={кто.error} />
      : <Outlet key={companyId} />

  // Пути «Телефонии» — полноэкранные (`WORKSPACE_PATHS`): оболочка не прокручивает, прокрутка своя.
  // На телефоне запас снизу под нижнюю навигацию и плашку установки, как у «Трека» и «Конференций».
  const экран = (
    <div className="min-h-0 min-w-0 flex-1 overflow-y-auto"
      style={узкий ? { paddingBottom: 'calc(var(--pwa-install-height, 0px) + 6rem + env(safe-area-inset-bottom))' } : undefined}>
      <VoiceDataSourceBar state={source} pathname={pathname} />
      {содержимое}
    </div>
  )
  if (!компакт) return <div className="flex h-full min-h-0">{экран}</div>

  return (
    <div className="flex h-full min-h-0 flex-col">
      <nav aria-label="Разделы Телефонии" className="shrink-0 border-b border-border bg-card p-2">
        <select aria-label="Раздел Телефонии" value={voicePath(voiceViewFor(pathname))}
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
      {экран}
    </div>
  )
}

/** Пока узел проверяет пропуск, экран не пуст и не шлёт запросы раздела раньше `/me`. */
function AccessLoading() {
  return (
    <div role="status" aria-label="Проверяем доступ к Телефонии" className="flex flex-col gap-4 p-4">
      <span className="sr-only">Проверяем доступ к Телефонии…</span>
      <Skeleton className="h-7 w-48" />
      <Skeleton className="h-20 w-full rounded-xl" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-24 rounded-xl" />)}
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
