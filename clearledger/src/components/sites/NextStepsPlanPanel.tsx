/**
 * «Ближайшие шаги» — план работы по датам, а не по объектам.
 *
 * Отдел развития спросил: «формирование плана работы (следующий шаг по датам)?»
 * (замечание 06.08.2026). Данные для него уже есть в каждом проекте — «Следующий
 * шаг» и «Срок» на вкладке «Работа», — но собрать из них СВОЮ неделю было негде:
 * реестр проектов сортируется по объекту, а план работ по парку показывает
 * переносы и демонтажи, где стройки нет вовсе.
 *
 * Ось экрана — ДАТА: просрочено, сегодня, эта неделя, дальше, без срока. Внутри
 * группы строка отвечает на «что делаю» — шаг, проект, стадия, кто ведёт.
 * Проекты без срока стоят последней группой намеренно: это не «свободные», а
 * незапланированные, и их видно как дырку в плане.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Loader2, CalendarClock, AlertTriangle } from 'lucide-react'
import { getProjects, STAGE_META } from '@/services/sitesService'
import { inWork, planBuckets } from '@/lib/projectPlan'
import { formatDate } from '@/lib/formatDate'
import { plural } from '@/lib/textUtils'
import { useAuth } from '@/contexts/AuthContext'
import { useOpenProject } from './useOpenProject'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

const iso = (d: Date) => d.toISOString().slice(0, 10)
// Дата всегда с годом: без него срок 11.01.2027 в списке неотличим от января
// текущего года, а такие проекты в плане есть (проверка 25.10.2026).
const fmt = (s?: string | null) => (s ? formatDate(s) : '—')

export function NextStepsPlanPanel({ companyId }: { companyId: string }) {
  const [search, setSearch] = useState('')
  const [mine, setMine] = useState(false)
  const openProject = useOpenProject()

  const q = useQuery({
    queryKey: ['pr-next-steps', companyId],
    queryFn: () => getProjects(companyId, {}),
  })
  // «Мои» считаем по имени ответственного: в строке реестра приезжает именно оно
  // (`ownerName`), а не id. Первый вопрос к плану — «что на мне».
  const { user } = useAuth()
  const me = user?.name ?? null

  const buckets = useMemo(() => {
    const now = new Date()
    const today = iso(now)
    const weekEnd = iso(new Date(now.getTime() + 7 * 86400_000))
    const needle = search.trim().toLowerCase()

    const rows = (q.data ?? []).filter((p) => {
      if (!inWork(p)) return false
      if (mine && me && p.ownerName !== me) return false
      if (!needle) return true
      return [p.projectNo, p.title, p.nextAction, p.ownerName, p.site?.address, p.site?.region]
        .some((v) => (v ?? '').toLowerCase().includes(needle))
    })

    return planBuckets(rows, today, weekEnd)
  }, [q.data, search, mine, me])

  if (q.isLoading) {
    return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
  }

  const total = buckets.reduce((a, b) => a + b.items.length, 0)
  const overdue = buckets.find((b) => b.key === 'overdue')?.items.length ?? 0

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div data-zone="Ближайшие шаги по проектам">
          <p className="text-sm text-muted-foreground">
            {nf0.format(total)} {plural(total, 'проект', 'проекта', 'проектов')} в работе
            {overdue > 0 && <>, просрочено <span className="text-red-600 dark:text-red-400">{nf0.format(overdue)}</span></>}.
            Дата берётся из «Ближайшего результата» на вкладке «Обзор» карточки проекта.
            Замороженные, отклонённые и проекты интеграции в план не входят.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <Input className="h-10 sm:h-8 w-full sm:w-[260px] text-sm" value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Шаг, проект, адрес, ответственный" />
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} disabled={!me} />
            только мои
          </label>
        </div>
      </div>

      {buckets.length === 0 ? (
        <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">
          Проектов в работе нет — планировать нечего.
        </CardContent></Card>
      ) : buckets.map((b) => (
        <Card key={b.key}>
          <div className={`flex flex-wrap items-baseline gap-2 border-b px-3 py-2 ${b.alarm ? 'bg-red-500/5' : 'bg-muted/40'}`}>
            <span className={`text-sm font-semibold ${b.alarm ? 'text-red-600 dark:text-red-400' : ''}`}>
              {b.alarm && <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />}{b.label}
            </span>
            <span className="text-xs text-muted-foreground">{b.items.length}</span>
            <span className="ml-auto text-xs text-muted-foreground">{b.hint}</span>
          </div>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <tbody>
                {b.items.map((p) => (
                  // Открываем по ПЛОЩАДКЕ (`siteId`), а не по id проекта: рабочий экран
                  // проекта грузится ручкой площадки, и с чужим ключом карточка
                  // отвечала «не найдено» и висела в загрузке (замечание 07.08.2026).
                  <tr key={p.id} className="cursor-pointer border-b border-border/30 last:border-0 hover:bg-accent/40"
                    onClick={() => openProject(p.siteId)}>
                    <td className="w-[92px] py-1.5 pl-3 font-mono text-xs text-muted-foreground align-top">
                      <span className="inline-flex items-center gap-1">
                        <CalendarClock className="h-3 w-3" />{fmt(p.nextActionDue)}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 align-top">
                      <div className={(p.nextAction ?? '').trim() ? '' : 'text-muted-foreground'}>
                        {(p.nextAction ?? '').trim() || 'следующий шаг не записан'}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {p.projectNo ?? p.title ?? '—'}
                        {p.site?.address ? ` · ${p.site.address}` : ''}
                      </div>
                    </td>
                    <td className="w-[170px] py-1.5 pr-2 align-top text-xs text-muted-foreground">
                      {STAGE_META[p.stage]?.label ?? p.stage}
                    </td>
                    <td className="w-[190px] py-1.5 pr-3 align-top text-xs text-muted-foreground">
                      {p.ownerName ?? 'без ответственного'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
