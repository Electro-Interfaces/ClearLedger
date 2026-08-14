/**
 * «Аудитор» — приложение агента: разговор и его настройка (docs/AUDITOR.md).
 *
 * Плитка на столе ведёт сюда. Панель справа и кнопка в шапке дают только разговор —
 * этого хватает, чтобы спросить по ходу работы. Здесь же живёт всё остальное:
 * чем агенту разрешено пользоваться, что он обязан помнить об этой компании, в каком
 * режиме отвечать и что он уже отвечал.
 *
 * Канон пространства: раздел один (`/auditor`), его пункты — во второй колонке
 * (`?view=`), заголовок экрана равен имени пункта. Геометрия взята у «Задач»
 * (`pages/tasks/TasksLayout.tsx`) — это такое же приложение Ядра.
 *
 * Не путать с `pages/partner/AuditorPage.tsx`: тот из партнёрского контура и
 * обслуживает внешние инстансы ClearLedger.
 */
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, ClipboardList, ListChecks, MessageSquare, Save, SlidersHorizontal } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { QueryError } from '@/components/common/QueryError'
import { AuditorPanel } from '@/components/auditor/AuditorPanel'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as auditor from '@/services/spaceAuditorService'

const VIEWS = [
  { key: 'chat', label: 'Разговор', icon: MessageSquare, hint: 'спросить про данные пространства' },
  { key: 'skills', label: 'Навыки', icon: ListChecks, hint: 'чем ему разрешено пользоваться' },
  { key: 'setup', label: 'Настройка', icon: SlidersHorizontal, hint: 'режим, указания компании, модели' },
  { key: 'runs', label: 'Журнал', icon: ClipboardList, hint: 'что спрашивали и что он нашёл' },
] as const

/** Оценка ответа в журнале. Цвета альфа-шкалой — один класс на обе темы. */
const VERDICTS: Record<auditor.AuditorVerdict, { label: string; cls: string }> = {
  ok: { label: 'верно', cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' },
  wrong: { label: 'неверно', cls: 'bg-red-500/10 text-red-600 dark:text-red-400' },
  not_an_issue: { label: 'не ошибка', cls: 'bg-amber-500/10 text-amber-600 dark:text-amber-400' },
}

const MODES = [
  { key: 'careful', label: 'Осторожный', hint: 'только то, что прямо следует из данных: без догадок о причинах и без советов' },
  { key: 'normal', label: 'Обычный', hint: 'ответ на вопрос плюс находки, если они есть' },
  { key: 'thorough', label: 'Дотошный', hint: 'смотрит шире: называет смежные проблемы и предлагает, что ещё проверить' },
] as const

export function AuditorPage() {
  const [params, setParams] = useSearchParams()
  const view = VIEWS.some((v) => v.key === params.get('view')) ? params.get('view')! : 'chat'
  const open = (key: string) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', key)
    return n
  }, { replace: true })

  return (
    <div className="flex h-full min-h-0">
      <nav data-zone="Пункты раздела" data-zone-side
        className="flex w-52 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border bg-card px-2.5 py-3 max-lg:hidden">
        {VIEWS.map((v) => (
          <button key={v.key} type="button" onClick={() => open(v.key)} title={v.hint}
            aria-current={v.key === view ? 'page' : undefined}
            className={cn('flex items-center gap-2 rounded-md px-3 py-1.5 text-left text-[13px] transition-colors',
              v.key === view
                ? 'bg-primary/10 font-medium text-primary'
                : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground')}>
            <v.icon className="size-4 shrink-0" />
            {v.label}
          </button>
        ))}
      </nav>

      {/* На узком экране пункты идут строкой сверху: колонка съела бы половину ширины. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-card px-2 py-1.5 lg:hidden">
          {VIEWS.map((v) => (
            <button key={v.key} type="button" onClick={() => open(v.key)}
              className={cn('min-h-10 shrink-0 whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs',
                v.key === view ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground')}>
              {v.label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1">
          {view === 'chat' && <ChatView />}
          {view === 'skills' && <SkillsView />}
          {view === 'setup' && <SetupView />}
          {view === 'runs' && <RunsView />}
        </div>
      </div>
    </div>
  )
}

/** Разговор во всю ширину. Каталог рядом — чтобы было видно, о чём вообще спрашивать. */
function ChatView() {
  const { data: skills } = useQuery({
    queryKey: ['auditor-skills'], queryFn: auditor.getSkills, staleTime: 10 * 60 * 1000, retry: false,
  })
  const groups = groupSkills(skills)

  return (
    <div className="flex h-full min-h-0 gap-4 p-4">
      <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-border/60 bg-card">
        <AuditorPanel />
      </div>
      <aside className="hidden w-80 shrink-0 flex-col overflow-y-auto rounded-xl border border-border/60 bg-card/50 p-4 xl:flex">
        <div className="mb-3 flex items-center gap-2">
          <Bot className="size-4 text-primary" />
          <h2 className="text-sm font-semibold">Что я умею спросить</h2>
        </div>
        {Object.entries(groups).map(([group, items]) => (
          <div key={group} className="mb-4">
            <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{group}</div>
            <ul className="space-y-1.5">
              {items.map((s) => (
                <li key={s.id} className="rounded-lg border border-border/50 px-2.5 py-1.5">
                  <div className="text-sm font-medium">{s.name}</div>
                  <div className="mt-0.5 text-xs leading-snug text-muted-foreground">{s.when}</div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </aside>
    </div>
  )
}

/** Навыки: переключатель на каждый. Выключенный не попадает даже в промпт выбора. */
function SkillsView() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const skills = useQuery({ queryKey: ['auditor-skills'], queryFn: auditor.getSkills, retry: false })
  const settings = useQuery({
    queryKey: ['auditor-settings', companyId],
    queryFn: () => auditor.getSettings(companyId), enabled: !!companyId,
  })
  const save = useMutation({
    mutationFn: (disabled: string[]) => auditor.saveSettings(companyId, {
      ...(settings.data as auditor.AuditorSettings), disabled_skills: disabled,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['auditor-settings', companyId] }); toast.success('Сохранено') },
    onError: (e: Error) => toast.error(e.message),
  })

  if (skills.error) return <div className="p-4"><QueryError message={(skills.error as Error).message} onRetry={() => skills.refetch()} /></div>
  const disabled = settings.data?.disabled_skills ?? []
  const groups = groupSkills(skills.data)

  const toggle = (id: string) =>
    save.mutate(disabled.includes(id) ? disabled.filter((x) => x !== id) : [...disabled, id])

  return (
    <div className="h-full overflow-y-auto p-4">
      <h1 className="text-lg font-semibold">Навыки</h1>
      <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
        Навык это именованный вопрос к данным, а не свободный запрос: агент выбирает из
        этого списка, поэтому любой его ответ можно повторить руками. Выключенный навык
        не попадает даже в выбор — агент о нём не узнает.
        {' '}Всего {skills.data?.length ?? 0}, выключено {disabled.length}.
      </p>

      {Object.entries(groups).map(([group, items]) => (
        <section key={group} className="mt-5">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{group}</div>
          <div className="space-y-1.5">
            {items.map((s) => {
              const off = disabled.includes(s.id)
              return (
                <div key={s.id}
                  className={cn('flex items-start gap-3 rounded-lg border px-3 py-2 transition-colors',
                    off ? 'border-border/40 bg-muted/30 opacity-60' : 'border-border/60 bg-card')}>
                  <Switch checked={!off} onCheckedChange={() => toggle(s.id)} disabled={save.isPending} className="mt-0.5" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{s.name}</div>
                    <div className="mt-0.5 text-xs leading-snug text-muted-foreground">{s.when}</div>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}

/** Настройка: режим, постоянные указания компании и выбор моделей. */
function SetupView() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['auditor-settings', companyId],
    queryFn: () => auditor.getSettings(companyId), enabled: !!companyId,
  })
  const [draft, setDraft] = useState<auditor.AuditorSettings | null>(null)
  useEffect(() => { if (data) setDraft(data) }, [data])

  const save = useMutation({
    mutationFn: (s: auditor.AuditorSettings) => auditor.saveSettings(companyId, s),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['auditor-settings', companyId] }); toast.success('Настройки сохранены') },
    onError: (e: Error) => toast.error(e.message),
  })

  if (error) return <div className="p-4"><QueryError message={(error as Error).message} onRetry={() => refetch()} /></div>
  if (isLoading || !draft) return <div className="p-4 text-sm text-muted-foreground">Загружаю…</div>

  const dirty = JSON.stringify(draft) !== JSON.stringify(data)

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">Настройка</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Действует на всех, кто спрашивает агента в этом пространстве, поэтому менять
            может администратор.
          </p>
        </div>
        <Button onClick={() => save.mutate(draft)} disabled={!dirty || save.isPending} className="gap-2 shrink-0">
          <Save className="size-4" />{save.isPending ? 'Сохраняю…' : 'Сохранить'}
        </Button>
      </div>

      <section className="mt-6 max-w-3xl">
        <h2 className="text-sm font-semibold">Режим</h2>
        <div className="mt-2 space-y-1.5">
          {MODES.map((m) => (
            <button key={m.key} type="button" onClick={() => setDraft({ ...draft, mode: m.key })}
              className={cn('block w-full rounded-lg border px-3 py-2 text-left transition-colors',
                draft.mode === m.key ? 'border-primary/50 bg-primary/5' : 'border-border/60 hover:bg-accent/40')}>
              <div className={cn('text-sm font-medium', draft.mode === m.key && 'text-primary')}>{m.label}</div>
              <div className="mt-0.5 text-xs leading-snug text-muted-foreground">{m.hint}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="mt-6 max-w-3xl">
        <h2 className="text-sm font-semibold">Указания компании</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          То, что агент обязан помнить в каждом ответе: особенности учёта, ставки, кого не
          трогать, как называть вещи. Эти строки важнее общих правил и едут в каждый запрос,
          поэтому пишите коротко и по делу.
        </p>
        <textarea
          value={draft.instructions ?? ''}
          onChange={(e) => setDraft({ ...draft, instructions: e.target.value })}
          rows={8}
          placeholder={'Например:\nНДС с 2026 года считаем по ставке 22 %.\nПоступления от ИП Морозова идут по договору без НДС.\nСоболеву Е. Н. в находки не включать — карточка ведётся вручную.'}
          className="mt-2 w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
        />
      </section>

      <section className="mt-6 max-w-3xl">
        <h2 className="text-sm font-semibold">Модели</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Пусто — берётся умолчание стека (выбор навыков дешёвой моделью, разбор данных
          сильной). Меняйте, когда ответы стали хуже или дороже, чем нужно.
        </p>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          {([['model_plan', 'Выбор навыков', 'haiku'], ['model_answer', 'Разбор данных', 'sonnet']] as const).map(
            ([field, label, ph]) => (
              <label key={field} className="block">
                <span className="text-xs text-muted-foreground">{label}</span>
                <input value={draft[field] ?? ''} placeholder={ph}
                  onChange={(e) => setDraft({ ...draft, [field]: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary" />
              </label>
            ))}
        </div>
      </section>
    </div>
  )
}

/** Журнал: что спрашивали, куда он смотрел, что нашёл. */
function RunsView() {
  const { companyId } = useCompany()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['auditor-runs', companyId],
    queryFn: () => auditor.getRuns(companyId), enabled: !!companyId,
  })
  if (error) return <div className="p-4"><QueryError message={(error as Error).message} onRetry={() => refetch()} /></div>

  const runs = data?.runs ?? []
  return (
    <div className="h-full overflow-y-auto p-4">
      <h1 className="text-lg font-semibold">Журнал</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        След работы агента: по нему видно, почему он ответил именно так и какие навыки при
        этом сработали.
      </p>
      {isLoading && <div className="mt-4 text-sm text-muted-foreground">Загружаю…</div>}
      {!isLoading && !runs.length && (
        <div className="mt-4 rounded-lg border border-border/60 bg-card/50 px-3 py-6 text-center text-sm text-muted-foreground">
          Пока ничего не спрашивали.
        </div>
      )}
      <div className="mt-4 space-y-2">
        {runs.map((r) => (
          <details key={r.id} className="rounded-lg border border-border/60 bg-card px-3 py-2">
            <summary className="cursor-pointer text-sm">
              <span className="font-medium">{r.question}</span>
              {r.verdict && (
                <span className={cn('ml-2 rounded px-1.5 py-0.5 text-[11px]', VERDICTS[r.verdict].cls)}>
                  {VERDICTS[r.verdict].label}
                </span>
              )}
              <span className="ml-2 text-xs text-muted-foreground">
                {r.user ? `${r.user} · ` : ''}
                {r.created_at ? new Date(r.created_at).toLocaleString('ru-RU') : ''}
                {r.duration_ms ? ` · ${Math.round(r.duration_ms / 1000)} с` : ''}
                {r.findings?.length ? ` · находок ${r.findings.length}` : ''}
              </span>
            </summary>
            <div className="mt-2 space-y-2 text-sm">
              {r.path && <div className="text-xs text-muted-foreground">Экран: {r.path}</div>}
              {!!r.skills?.length && (
                <div className="flex flex-wrap gap-1">
                  {r.skills.map((s) => (
                    <span key={s} className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{s}</span>
                  ))}
                </div>
              )}
              {/* Объяснение оценки — то, ради чего журнал и ведётся: из него растёт
                  правило исключения. Показываем выше ответа: разбирают именно его. */}
              {r.feedback && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-2.5 py-1.5">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-amber-600 dark:text-amber-400">
                    Замечание человека
                  </div>
                  <div className="mt-0.5 text-sm">{r.feedback}</div>
                </div>
              )}
              {r.answer && <div className="whitespace-pre-wrap text-muted-foreground">{r.answer}</div>}
            </div>
          </details>
        ))}
      </div>
    </div>
  )
}

function groupSkills(skills?: auditor.AuditorSkill[]) {
  return (skills || []).reduce<Record<string, auditor.AuditorSkill[]>>((acc, s) => {
    (acc[s.group] ||= []).push(s)
    return acc
  }, {})
}

export default AuditorPage
