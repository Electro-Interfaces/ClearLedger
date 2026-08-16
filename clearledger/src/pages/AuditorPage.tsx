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
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Bot, CheckCircle2, ClipboardList, FlaskConical, Download, GitCommitHorizontal, ListChecks, Loader2, MessageSquare, Plus, Save, SlidersHorizontal, TerminalSquare, Upload, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { QueryError } from '@/components/common/QueryError'
import { AuditorPanel } from '@/components/auditor/AuditorPanel'
import { AuditorTerminal } from '@/components/auditor/AuditorTerminal'
import { useCompany } from '@/contexts/CompanyContext'
import { cn } from '@/lib/utils'
import * as auditor from '@/services/spaceAuditorService'

const VIEWS = [
  { key: 'chat', label: 'Разговор', icon: MessageSquare, hint: 'спросить про данные пространства' },
  { key: 'skills', label: 'Навыки', icon: ListChecks, hint: 'чем ему разрешено пользоваться' },
  // Методы и знание — то, что агент НАЖИЛ, в отличие от навыков-ручек, которые приходят
  // с образом. Их и надо видеть отдельно: по ним понятно, растёт он или стоит.
  { key: 'methods', label: 'Методы', icon: Wrench, hint: 'чему научили: как отвечать на класс вопросов' },
  { key: 'knowledge', label: 'Знание', icon: BookOpen, hint: 'что он знает об этой компании' },
  { key: 'setup', label: 'Настройка', icon: SlidersHorizontal, hint: 'режим, указания компании, модели' },
  { key: 'runs', label: 'Журнал', icon: ClipboardList, hint: 'что спрашивали и что он нашёл' },
  // Мастерская — НАСТОЯЩИЙ Claude Code в терминале, без нашей прослойки. Отдельный
  // раздел, а не тумблер в чате: это другой инструмент, а не другой режим ответа.
  { key: 'workshop', label: 'Мастерская', icon: TerminalSquare, hint: 'Claude Code в рабочей папке агента', admin: true },
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
  const { companyId } = useCompany()
  const [params, setParams] = useSearchParams()
  const { data: health } = useQuery({
    queryKey: ['auditor-health'], queryFn: auditor.getHealth, staleTime: 5 * 60 * 1000, retry: false,
  })
  const { data: settings } = useQuery({
    queryKey: ['auditor-settings', companyId],
    queryFn: () => auditor.getSettings(companyId), enabled: !!companyId, retry: false,
  })
  const views = VIEWS.filter((v) => !('admin' in v && v.admin) || (health?.workshop && settings?.can_manage))
  const view = views.some((v) => v.key === params.get('view')) ? params.get('view')! : 'chat'
  const activeMobileTab = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    activeMobileTab.current?.scrollIntoView({ block: 'nearest', inline: 'center' })
  }, [view])
  const open = (key: string) => setParams((p) => {
    const n = new URLSearchParams(p)
    n.set('view', key)
    return n
  }, { replace: true })

  return (
    <div className="flex h-full min-h-0">
      <nav data-zone="Пункты раздела" data-zone-side
        className="flex w-52 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border bg-card px-2.5 py-3 max-lg:hidden">
        {views.map((v) => (
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
        <div className="scrollbar-hide flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-card px-2 py-1.5 lg:hidden">
          {views.map((v) => (
            <button key={v.key} ref={v.key === view ? activeMobileTab : undefined}
              type="button" onClick={() => open(v.key)}
              className={cn('min-h-10 shrink-0 whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs',
                v.key === view ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground')}>
              {v.label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1">
          {view === 'chat' && <ChatView />}
          {view === 'skills' && <SkillsView />}
          {view === 'methods' && <MethodsView />}
          {view === 'knowledge' && <KnowledgeView />}
          {view === 'setup' && <SetupView />}
          {view === 'runs' && <RunsView />}
          {view === 'workshop' && <AuditorTerminal />}
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
    <div className="flex h-full min-h-0 min-w-0 gap-4 p-3 sm:p-4">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col rounded-xl border border-border/60 bg-card">
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

/**
 * Правка файла агента прямо в разделе.
 *
 * Текст показывается как есть — это markdown, который читает сам агент, и подменять его
 * формой значило бы прятать то, что реально уходит в промпт. Сохранение доступно
 * администратору; правка сразу коммитится в рабочую папку его именем.
 */
function FileEditor({ path, body, canEdit, onSaved }: {
  path: string
  body: string
  canEdit: boolean
  onSaved: () => void
}) {
  const { companyId } = useCompany()
  const [draft, setDraft] = useState(body)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setDraft(body) }, [body])

  const dirty = draft !== body

  async function save() {
    setBusy(true)
    try {
      await auditor.saveAgentFile(companyId, path, draft)
      toast.success('Сохранено — агент прочитает это со следующего вопроса')
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-2">
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        readOnly={!canEdit}
        rows={Math.min(30, Math.max(8, draft.split('\n').length + 1))}
        className={cn('w-full resize-y rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs leading-relaxed outline-none',
          canEdit ? 'focus:border-primary' : 'text-muted-foreground')}
      />
      <div className="mt-1.5 flex items-center gap-2">
        {canEdit ? (
          <>
            <Button size="sm" onClick={save} disabled={!dirty || busy} className="gap-2">
              <Save className="size-4" />{busy ? 'Сохраняю…' : 'Сохранить'}
            </Button>
            {dirty && <Button size="sm" variant="ghost" onClick={() => setDraft(body)}>Отменить</Button>}
            <span className="text-xs text-muted-foreground">{path}</span>
          </>
        ) : (
          <span className="text-xs text-muted-foreground">Править может администратор пространства · {path}</span>
        )}
      </div>
    </div>
  )
}

/** Методы: чему агента научили. Видно, что уже проверено, а что ещё гипотеза. */
function MethodsView() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const { data: settings } = useQuery({
    queryKey: ['auditor-settings', companyId],
    queryFn: () => auditor.getSettings(companyId), enabled: !!companyId, retry: false,
  })
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['auditor-methods'], queryFn: auditor.getMethods, retry: false,
  })
  const [open, setOpen] = useState<string | null>(null)

  if (error) return <div className="p-4"><QueryError message={(error as Error).message} onRetry={() => refetch()} /></div>

  const methods = data ?? []
  const verified = methods.filter((m) => m.verified).length

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">Методы</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Чему агента научили: как отвечать на класс вопросов — что смотреть, в каком порядке,
            что считать находкой. В отличие от навыков, методы не приходят с обновлением —
            они наживаются здесь, в работе, и лежат файлами в рабочей папке под версиями.
            {methods.length > 0 && <> Всего {methods.length}, проверено {verified}.</>}
          </p>
        </div>
        {/* Наработка живёт в томе ОДНОГО стека: без выгрузки метод, проверенный здесь, не
            попадёт ни на соседнее пространство, ни в следующее развёрнутое. */}
        {settings?.can_manage && (
          <div className="shrink-0 text-right">
            <Button variant="outline" size="sm"
              onClick={() => auditor.exportWork().catch((e: Error) => toast.error(e.message))}>
              <Download className="mr-1 size-3.5" />Выгрузить для поставки
            </Button>
            <p className="mt-1 max-w-56 text-[11px] text-muted-foreground">
              методы, скрипты и общее знание — без данных организаций
            </p>
          </div>
        )}
      </div>

      {isLoading && <div className="mt-4 text-sm text-muted-foreground">Загружаю…</div>}
      {!isLoading && !methods.length && (
        <div className="mt-4 rounded-lg border border-border/60 bg-card/50 px-3 py-6 text-center text-sm text-muted-foreground">
          Методов пока нет. Первый появится после разбора в мастерской.
        </div>
      )}

      <div className="mt-4 space-y-2">
        {methods.map((m) => (
          <div key={m.id} className="rounded-lg border border-border/60 bg-card px-3 py-2">
            <button type="button" onClick={() => setOpen(open === m.id ? null : m.id)}
              className="flex w-full items-start gap-2 text-left">
              {m.verified
                ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                : <FlaskConical className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />}
              <span className="min-w-0 flex-1">
                <span className="font-medium">{m.name}</span>
                <span className={cn('ml-2 rounded px-1.5 py-0.5 text-[11px]',
                  m.verified
                    ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                    : 'bg-amber-500/10 text-amber-600 dark:text-amber-400')}>
                  {m.verified ? 'проверен' : 'черновик'}
                </span>
                <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">{m.description}</span>
              </span>
            </button>
            {open === m.id && (
              <>
                {/* Техническое имя нужно, только когда метод открыли: по нему ищут файл в
                    рабочей папке. В списке оно занимало место названия и ничего не значило
                    для человека — CLI требует латиницу, но это его дело, а не читателя. */}
                <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                  .claude/skills/{m.id}/SKILL.md
                </div>
                {m.proof && (
                  <div className="mt-2 rounded-lg border border-emerald-500/40 bg-emerald-500/5 px-2.5 py-1.5">
                    <div className="text-[11px] font-medium uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
                      Чем проверено
                    </div>
                    <div className="mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground">{m.proof.slice(0, 600)}</div>
                  </div>
                )}
                <FileEditor path={`.claude/skills/${m.id}/SKILL.md`} body={m.body}
                  canEdit={!!settings?.can_manage}
                  onSaved={() => qc.invalidateQueries({ queryKey: ['auditor-methods'] })} />
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Знание: что агент знает об этой компании, и как оно росло. */
function KnowledgeView() {
  const { companyId } = useCompany()
  const qc = useQueryClient()
  const { data: settings } = useQuery({
    queryKey: ['auditor-settings', companyId],
    queryFn: () => auditor.getSettings(companyId), enabled: !!companyId, retry: false,
  })
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['auditor-knowledge', companyId],
    queryFn: () => auditor.getKnowledge(companyId), enabled: !!companyId, retry: false,
  })
  const { data: growth } = useQuery({
    queryKey: ['auditor-growth'], queryFn: auditor.getGrowth, retry: false,
  })
  const [open, setOpen] = useState<string | null>(null)
  const reload = () => qc.invalidateQueries({ queryKey: ['auditor-knowledge', companyId] })
  const canEdit = !!settings?.can_manage

  if (error) return <div className="p-4"><QueryError message={(error as Error).message} onRetry={() => refetch()} /></div>

  const all = data ?? []
  // Два слоя не смешиваем в один список: правило «у этого клиента УСН» и общая методика
  // живут по-разному, и человек должен видеть, что именно он правит — знание про одну
  // организацию или знание, которое поедет ко всем клиентам фирмы.
  const LAYERS = [
    {
      scope: 'company' as const,
      title: 'Знание об этой организации',
      hint: 'Едет в ответы только про неё: особенности учёта, исключения, загруженные документы, '
        + 'уточнения к общим методам под её специфику.',
    },
    {
      scope: 'space' as const,
      title: 'Знание пространства',
      hint: 'Общее для всех клиентов: методика, нормативы, словарь. Правка здесь меняет ответы '
        + 'по каждой организации сразу.',
    },
  ]

  return (
    <div className="h-full overflow-y-auto p-4">
      <h1 className="text-lg font-semibold">Знание</h1>
      <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
        То, что агент читает перед каждым ответом. Стоит выше общих правил — поэтому правка
        здесь меняет ответы сразу, без перезапуска.
      </p>

      {isLoading && <div className="mt-4 text-sm text-muted-foreground">Загружаю…</div>}

      {LAYERS.map((layer) => {
        const items = all.filter((k) => k.scope === layer.scope)
        return (
          <section key={layer.scope} className="mt-6 max-w-3xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">{layer.title}</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">{layer.hint}</p>
              </div>
              {layer.scope === 'company' && canEdit && <KnowledgeAdd companyId={companyId} onDone={reload} />}
            </div>

            {!isLoading && !items.length && (
              <p className="mt-2 rounded-lg border border-dashed border-border/60 px-3 py-4 text-sm text-muted-foreground">
                {layer.scope === 'company'
                  ? 'Пока пусто. Загрузите учётную политику, приказ или регламент — или напишите текстом, '
                    + 'что агенту нужно знать именно про эту организацию.'
                  : 'Пусто.'}
              </p>
            )}

            <div className="mt-2 space-y-2">
              {items.map((k) => (
                <div key={k.file} className="rounded-lg border border-border/60 bg-card px-3 py-2">
                  <button type="button" onClick={() => setOpen(open === k.file ? null : k.file)}
                    className="flex w-full items-center gap-2 text-left">
                    <BookOpen className="size-4 shrink-0 text-muted-foreground" />
                    <span className="font-medium">{k.title}</span>
                    {k.generated && (
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                        пересчитывается
                      </span>
                    )}
                    <span className="ml-auto text-xs text-muted-foreground">
                      {new Date(k.updated).toLocaleDateString('ru-RU')}
                    </span>
                  </button>
                  {open === k.file && (
                    <>
                      {k.generated && (
                        <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                          Файл пересчитывается скриптом — правка руками затрётся при следующем пересчёте.
                        </p>
                      )}
                      <FileEditor path={`knowledge/${k.file}`} body={k.body}
                        canEdit={canEdit} onSaved={reload} />
                      {k.scope === 'company' && canEdit && (
                        <button type="button"
                          onClick={() => {
                            if (!confirm(`Убрать «${k.title}» из знания организации?`)) return
                            auditor.deleteAgentFile(companyId, `knowledge/${k.file}`)
                              .then(() => { setOpen(null); reload(); toast.success('Убрано из знания') })
                              .catch((e: Error) => toast.error(e.message))
                          }}
                          className="mt-2 text-xs text-red-600 hover:underline dark:text-red-400">
                          Убрать из знания
                        </button>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
          </section>
        )
      })}

      {!!growth?.length && (
        <section className="mt-6 max-w-3xl">
          <h2 className="text-sm font-semibold">Как рос</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            История рабочей папки: что и когда менялось в знании и методах.
          </p>
          <ul className="mt-2 space-y-1">
            {growth.map((g) => (
              <li key={g.hash} className="flex items-start gap-2 text-sm">
                <GitCommitHorizontal className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  {g.subject}
                  <span className="ml-2 text-xs text-muted-foreground">
                    {g.author} · {new Date(g.date).toLocaleString('ru-RU')}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

/**
 * Пополнить знание организации: загрузить документ или написать своё.
 *
 * Имя файла на диске не спрашиваем — оно техническое и человеку неинтересно. Человек
 * даёт заголовок, он же становится первой строкой файла и именем в списке.
 */
function KnowledgeAdd({ companyId, onDone }: { companyId: string; onDone: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [title, setTitle] = useState<string | null>(null)

  const upload = (f?: File | null) => {
    if (!f) return
    setBusy(true)
    auditor.uploadKnowledge(companyId, f)
      .then((r) => { toast.success(`«${r.title}» в знании: ${r.chars.toLocaleString('ru-RU')} знаков`); onDone() })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => { setBusy(false); if (fileRef.current) fileRef.current.value = '' })
  }

  const create = () => {
    const t = (title ?? '').trim()
    if (!t) return
    // Имя файла — техническое и латиницей: по нему ходит белый список правки на сервисе.
    // Заголовок кириллицей живёт внутри файла, и в списке видно именно его.
    auditor.saveAgentFile(companyId, `knowledge/${companyId}/zapis-${Date.now()}.md`, `# ${t}\n\n`)
      .then(() => { setTitle(null); onDone(); toast.success('Создано — откройте и напишите текст') })
      .catch((e: Error) => toast.error(e.message))
  }

  return (
    <div className="shrink-0 text-right">
      <div className="flex items-center gap-2">
        <input ref={fileRef} type="file" className="hidden"
          accept=".md,.txt,.pdf,.docx,.doc,.xlsx,.xls,.csv,.json,.xml"
          onChange={(e) => upload(e.target.files?.[0])} />
        <Button variant="outline" size="sm" disabled={busy} onClick={() => fileRef.current?.click()}>
          {busy ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <Upload className="mr-1 size-3.5" />}
          Загрузить документ
        </Button>
        <Button variant="outline" size="sm" onClick={() => setTitle(title === null ? '' : null)}>
          <Plus className="mr-1 size-3.5" />Написать
        </Button>
      </div>
      {title !== null && (
        <div className="mt-2 flex items-center gap-2">
          <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') create(); if (e.key === 'Escape') setTitle(null) }}
            placeholder="О чём это знание — например «Учётная политика 2026»"
            className="w-72 rounded-md border border-border/60 bg-background px-2 py-1 text-sm" />
          <Button size="sm" onClick={create} disabled={!title.trim()}>Создать</Button>
        </div>
      )}
      <p className="mt-1 text-[11px] text-muted-foreground">
        Word, PDF и таблицы переводятся в текст при загрузке
      </p>
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
