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
import { getProjects, STAGE_META, type ProjectRow } from '@/services/sitesService'
import { useAuth } from '@/contexts/AuthContext'
import { useOpenProject } from './useOpenProject'

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const dm = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit' })

const iso = (d: Date) => d.toISOString().slice(0, 10)
const fmt = (s?: string | null) => (s ? dm.format(new Date(s)) : '—')

/** Группы плана: порядок — от «горит» к «не назначено». */
type Bucket = { key: string; label: string; hint: string; items: ProjectRow[]; alarm?: boolean }

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

  const buckets = useMemo<Bucket[]>(() => {
    const today = iso(new Date())
    const weekEnd = iso(new Date(Date.now() + 7 * 86400_000))
    const needle = search.trim().toLowerCase()

    const rows = (q.data ?? []).filter((p) => {
      // Архив и закрытые в плане не участвуют: работать по ним нечего.
      if (p.stage === 'archive' || p.closedOn) return false
      if (mine && me && p.ownerName !== me) return false
      if (!needle) return true
      return [p.projectNo, p.title, p.nextAction, p.ownerName, p.site?.address, p.site?.region]
        .some((v) => (v ?? '').toLowerCase().includes(needle))
    })

    const has = (p: ProjectRow) => !!(p.nextAction ?? '').trim()
    const due = (p: ProjectRow) => p.nextActionDue ?? null

    const pick = (fn: (p: ProjectRow) => boolean) =>
      rows.filter(fn).sort((a, b) => (due(a) ?? '9999').localeCompare(due(b) ?? '9999'))

    return [
      {
        key: 'overdue', label: 'Просрочено', alarm: true,
        hint: 'Срок шага прошёл — либо делаем, либо переносим дату честно',
        items: pick((p) => !!due(p) && due(p)! < today),
      },
      {
        key: 'today', label: 'Сегодня',
        hint: 'Сегодняшний срок',
        items: pick((p) => due(p) === today),
      },
      {
        key: 'week', label: 'Ближайшая неделя',
        hint: 'Следующие семь дней',
        items: pick((p) => !!due(p) && due(p)! > today && due(p)! <= weekEnd),
      },
      {
        key: 'later', label: 'Дальше',
        hint: 'Запланировано за горизонтом недели',
        items: pick((p) => !!due(p) && due(p)! > weekEnd),
      },
      {
        key: 'nodate', label: 'Шаг есть, срока нет',
        hint: 'Работа названа, но не поставлена в план — по ней нельзя спросить',
        items: pick((p) => has(p) && !due(p)),
      },
      {
        key: 'nostep', label: 'Шаг не назначен',
        hint: 'Проект в работе, а что делать дальше — не записано',
        items: pick((p) => !has(p)),
      },
    ].filter((b) => b.items.length > 0)
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
            {nf0.format(total)} проектов в работе
            {overdue > 0 && <>, просрочено <span className="text-red-600 dark:text-red-400">{nf0.format(overdue)}</span></>}.
            Шаг и срок ставятся в карточке проекта, вкладка «Работа».
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
