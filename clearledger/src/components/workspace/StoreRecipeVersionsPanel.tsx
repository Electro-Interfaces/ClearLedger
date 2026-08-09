import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2, ChefHat, CircleAlert, Clock3, GitBranch, PackageCheck,
  Plus, RefreshCw, Save, Send, Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useCompany } from '@/contexts/CompanyContext'
import {
  activateStoreRecipe, bootstrapStoreRecipes, createStoreRecipeDraft,
  getStoreRecipeWorkspace, pushStoreRecipes, updateStoreRecipeDraft,
  type StoreRecipeEntry, type StoreRecipeKind, type StoreRecipeLine,
  type StoreRecipeVersion,
} from '@/services/storeService'
import { StoreCommercialPolicyNotice } from './StoreCommercialPolicyNotice'
import { useCentralCommercialWrite } from './useStoreCommercialPolicy'

const KIND_LABEL: Record<StoreRecipeKind, string> = {
  dish: 'Блюдо', semi: 'Полуфабрикат', combo: 'Комбо',
}

const DELIVERY_LABEL: Record<string, string> = {
  applied: 'Применён', queued: 'В очереди', delivered: 'Получен агентом',
  mismatch: 'Не применён', outdated: 'Устарел', not_sent: 'Не отправлен',
}

const DELIVERY_STYLE: Record<string, string> = {
  applied: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  queued: 'border-sky-500/30 bg-sky-500/10 text-sky-300',
  delivered: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  mismatch: 'border-red-500/30 bg-red-500/10 text-red-300',
  outdated: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  not_sent: 'border-border bg-muted/30 text-muted-foreground',
}

type LocalLine = StoreRecipeLine & { key: string }

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Неизвестная ошибка'
}

function shortBundle(value: string | null | undefined): string {
  return value ? value.replace(/^ttk-/, '').slice(0, 10) : '—'
}

function localDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'
}

function sourceLabel(version: StoreRecipeVersion): string {
  if (version.source === 'station') return `АЗС ${version.source_station_id ?? '—'}`
  if (version.source === 'import') return 'исходный импорт'
  return 'центр'
}

function SummaryCard({ icon: Icon, label, value, hint, alarm }: {
  icon: typeof ChefHat; label: string; value: string | number; hint: string; alarm?: boolean
}) {
  return (
    <div className={`rounded-xl border p-4 ${alarm ? 'border-amber-500/30 bg-amber-500/5' : 'border-border bg-card'}`}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground"><Icon className="h-4 w-4" />{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>
    </div>
  )
}

function VersionBadge({ version }: { version: StoreRecipeVersion }) {
  const active = version.status === 'active' && version.valid_from && new Date(version.valid_from) <= new Date()
  const label = version.status === 'draft' ? 'черновик' : active ? 'действует' : version.status === 'active' ? 'запланирована' : 'архив'
  const style = version.status === 'draft'
    ? 'border-amber-500/30 text-amber-300'
    : active ? 'border-emerald-500/30 text-emerald-300' : 'border-border text-muted-foreground'
  return <span className={`rounded-full border px-2 py-0.5 text-[10px] ${style}`}>v{version.version} · {label}</span>
}

function RecipeEditor({ entry, createNew, canWrite, onChanged }: {
  entry?: StoreRecipeEntry
  createNew?: boolean
  canWrite: boolean
  onChanged: (dishUuid?: string) => void
}) {
  const source = entry?.draft ?? entry?.active
  const editable = canWrite && (createNew || Boolean(entry?.draft))
  const [dishUuid, setDishUuid] = useState(source?.dish_uuid ?? '')
  const [name, setName] = useState(source?.dish_name ?? '')
  const [kind, setKind] = useState<StoreRecipeKind>(source?.recipe_kind ?? 'dish')
  const [output, setOutput] = useState(String(source?.output_qty ?? 1))
  const [outputUnit, setOutputUnit] = useState(source?.output_unit ?? 'шт')
  const [lines, setLines] = useState<LocalLine[]>(
    source?.lines.map((line, index) => ({ ...line, key: `line-${index}` }))
      ?? [{ key: 'line-new', item: '', name: '', qty: 1, unit: 'шт' }],
  )
  const [effective, setEffective] = useState('')
  const [dirty, setDirty] = useState(false)
  const queryClient = useQueryClient()
  const queryKey = ['store-recipe-versions']

  const refresh = async (uuid?: string) => {
    await queryClient.invalidateQueries({ queryKey })
    onChanged(uuid)
  }

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        dish_name: name.trim(), recipe_kind: kind, output_qty: Number(output), output_unit: outputUnit.trim(),
        lines: lines.map((line) => ({ item: line.item, name: line.name, qty: Number(line.qty), unit: line.unit })),
      }
      if (createNew) return createStoreRecipeDraft({ dish_uuid: dishUuid.trim(), ...payload })
      if (!entry?.draft) throw new Error('Сначала создайте новую версию')
      return updateStoreRecipeDraft(entry.draft.id, payload)
    },
    onSuccess: async (version) => {
      setDirty(false)
      toast.success(`ТТК сохранена как v${version.version}`)
      await refresh(version.dish_uuid)
    },
    onError: (error) => toast.error('Не удалось сохранить ТТК', { description: errorText(error) }),
  })

  const clone = useMutation({
    mutationFn: () => createStoreRecipeDraft({ dish_uuid: entry!.dish_uuid }),
    onSuccess: async (version) => {
      toast.success(`Создан черновик v${version.version}`)
      await refresh(version.dish_uuid)
    },
    onError: (error) => toast.error('Не удалось создать версию', { description: errorText(error) }),
  })

  const activate = useMutation({
    mutationFn: () => activateStoreRecipe(entry!.draft!.id, effective ? new Date(effective).toISOString() : undefined),
    onSuccess: async (version) => {
      toast.success(effective ? `Версия v${version.version} запланирована` : `Версия v${version.version} введена в действие`)
      await refresh(version.dish_uuid)
    },
    onError: (error) => toast.error('ТТК не введена в действие', { description: errorText(error) }),
  })

  const updateLine = (key: string, field: keyof StoreRecipeLine, value: string) => {
    setDirty(true)
    setLines((current) => current.map((line) => line.key === key
      ? { ...line, [field]: field === 'qty' ? Number(value) : value }
      : line))
  }

  if (!source && !createNew) {
    return <div className="grid min-h-72 place-items-center rounded-xl border border-dashed border-border text-sm text-muted-foreground">Выберите ТТК слева</div>
  }

  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border p-4">
        <div>
          <div className="flex items-center gap-2">
            <h4 className="font-semibold">{createNew ? 'Новая ТТК' : source?.dish_name}</h4>
            {source && <VersionBadge version={source} />}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Полуфабрикаты и блюда внутри комбо раскроются до сырья на станции автоматически.
          </p>
		  {source && (
			<p className={`mt-2 text-xs ${source.source === 'station' ? 'text-amber-300' : 'text-muted-foreground'}`}>
			  Источник: {sourceLabel(source)}{source.change_note ? ` · ${source.change_note}` : ''}
			</p>
		  )}
        </div>
        {!editable && entry?.active && (
          <Button size="sm" variant="outline" onClick={() => clone.mutate()} disabled={clone.isPending}>
            <GitBranch />Новая версия
          </Button>
        )}
      </div>

      <div className="space-y-5 p-4">
        <div className="grid gap-3 md:grid-cols-[1.3fr_0.8fr_0.5fr_0.5fr]">
          <label className="space-y-1 text-xs text-muted-foreground">
            Наименование
            <input value={name} onChange={(event) => { setName(event.target.value); setDirty(true) }} disabled={!editable}
              className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground disabled:opacity-60" />
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">
            Вид
            <select value={kind} onChange={(event) => { setKind(event.target.value as StoreRecipeKind); setDirty(true) }} disabled={!editable}
              className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground disabled:opacity-60">
              {Object.entries(KIND_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">
            Выход
            <input type="number" min="0.000001" step="any" value={output} onChange={(event) => { setOutput(event.target.value); setDirty(true) }} disabled={!editable}
              className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground disabled:opacity-60" />
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">
            Единица выхода
            <input value={outputUnit} onChange={(event) => { setOutputUnit(event.target.value); setDirty(true) }} disabled={!editable}
              className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground disabled:opacity-60" />
          </label>
        </div>

        <label className="block space-y-1 text-xs text-muted-foreground">
          UUID блюда или полуфабриката
          <input value={dishUuid} onChange={(event) => { setDishUuid(event.target.value); setDirty(true) }} disabled={!createNew}
            className="h-10 w-full rounded-lg border border-border bg-background px-3 font-mono text-xs text-foreground disabled:opacity-60" />
        </label>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <div>
              <h5 className="text-sm font-medium">Состав на указанный выход</h5>
              <p className="text-xs text-muted-foreground">UUID может указывать как на сырьё, так и на другую ТТК.</p>
            </div>
            {editable && (
              <Button size="xs" variant="outline" onClick={() => {
                setDirty(true)
                setLines((current) => [...current, { key: `line-${Date.now()}`, item: '', name: '', qty: 1, unit: 'шт' }])
              }}><Plus />Компонент</Button>
            )}
          </div>
          <div className="space-y-2">
            {lines.map((line) => (
              <div key={line.key} className="grid gap-2 rounded-lg border border-border/60 bg-background/40 p-2 md:grid-cols-[1.2fr_1.4fr_0.5fr_0.5fr_auto]">
                <input value={line.item} onChange={(event) => updateLine(line.key, 'item', event.target.value)} disabled={!editable}
                  aria-label="UUID компонента" placeholder="UUID компонента" className="h-9 min-w-0 rounded-md border border-border bg-background px-2 font-mono text-[11px] disabled:opacity-60" />
                <input value={line.name} onChange={(event) => updateLine(line.key, 'name', event.target.value)} disabled={!editable}
                  aria-label="Наименование компонента" placeholder="Наименование" className="h-9 min-w-0 rounded-md border border-border bg-background px-2 text-xs disabled:opacity-60" />
                <input type="number" min="0.000001" step="any" value={line.qty} onChange={(event) => updateLine(line.key, 'qty', event.target.value)} disabled={!editable}
                  aria-label="Количество компонента" className="h-9 min-w-0 rounded-md border border-border bg-background px-2 text-xs disabled:opacity-60" />
                <input value={line.unit} onChange={(event) => updateLine(line.key, 'unit', event.target.value)} disabled={!editable}
                  aria-label="Единица компонента" placeholder="ед." className="h-9 min-w-0 rounded-md border border-border bg-background px-2 text-xs disabled:opacity-60" />
                {editable && (
                  <Button size="icon-xs" variant="ghost" aria-label="Удалить компонент"
                    onClick={() => { setDirty(true); setLines((current) => current.filter((item) => item.key !== line.key)) }}>
                    <Trash2 />
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>

        {editable && (
          <div className="flex flex-wrap items-end justify-between gap-3 border-t border-border pt-4">
            <Button variant="outline" onClick={() => save.mutate()} disabled={save.isPending}>
              <Save />{save.isPending ? 'Сохраняем…' : createNew ? 'Создать черновик' : 'Сохранить'}
            </Button>
            {!createNew && entry?.draft && (
              <div className="flex flex-wrap items-end gap-2">
                <label className="space-y-1 text-xs text-muted-foreground">
                  Действует с
                  <input type="datetime-local" value={effective} onChange={(event) => setEffective(event.target.value)}
                    className="block h-10 rounded-lg border border-border bg-background px-3 text-sm text-foreground" />
                </label>
                <Button onClick={() => activate.mutate()} disabled={dirty || activate.isPending || save.isPending}
                  title={dirty ? 'Сначала сохраните изменения' : undefined}>
                  <CheckCircle2 />{activate.isPending ? 'Проверяем…' : 'Ввести в действие'}
                </Button>
              </div>
            )}
          </div>
        )}

		{!createNew && entry && entry.history.length > 0 && (
		  <div className="border-t border-border pt-4">
			<h5 className="text-sm font-medium">История версий</h5>
			<div className="mt-2 space-y-2">
			  {entry.history.map((version) => (
				<details key={version.id} className="rounded-lg border border-border/60 bg-background/30 px-3 py-2">
				  <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 text-xs">
					<span className="font-medium">v{version.version} · {sourceLabel(version)}</span>
					<span className="text-muted-foreground">{localDate(version.created_at)}</span>
				  </summary>
				  <div className="mt-2 text-xs text-muted-foreground">
					{version.change_note && <p className="mb-2">{version.change_note}</p>}
					<ul className="space-y-1">
					  {version.lines.map((line) => <li key={line.item}>{line.name} — {line.qty} {line.unit}</li>)}
					</ul>
				  </div>
				</details>
			  ))}
			</div>
		  </div>
		)}
      </div>
    </div>
  )
}

export function StoreRecipeVersionsPanel() {
  const centralWrite = useCentralCommercialWrite()
  const { company } = useCompany()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  // Раскрытая станция: список того, что мешает её блюдам. Свёрнуто по умолчанию —
  // сеть смотрят сводкой, разбираются по одной точке.
  const [открыта] = useState<number | null>(null)
  const query = useQuery({
    queryKey: ['store-recipe-versions', company.id],
    queryFn: getStoreRecipeWorkspace,
    refetchInterval: 60_000,
  })

  const refresh = async () => queryClient.invalidateQueries({ queryKey: ['store-recipe-versions'] })
  const bootstrap = useMutation({
    mutationFn: bootstrapStoreRecipes,
    onSuccess: async (result) => {
      toast.success(`Перенесено ${result.created} ТТК в версионный реестр`)
      await refresh()
    },
    onError: (error) => toast.error('Не удалось перенести ТТК', { description: errorText(error) }),
  })
  const push = useMutation({
    mutationFn: pushStoreRecipes,
    onSuccess: async (result) => {
      const description = result.already_current ? 'На станции уже этот набор' : result.already_queued ? 'Набор уже ждёт доставки' : 'Набор поставлен в очередь'
      toast.success(`ТТК для АЗС ${push.variables}`, { description })
      await refresh()
    },
    onError: (error) => toast.error('Набор не отправлен', { description: errorText(error) }),
  })

  if (query.isLoading) return <div className="p-6 text-sm text-muted-foreground">Загрузка ТТК…</div>
  if (query.error) return <div className="p-6 text-sm text-red-400">Не удалось загрузить ТТК: {errorText(query.error)}</div>
  if (!query.data) return null

  const data = query.data
  const selectedDish = selected ?? data.recipes[0]?.dish_uuid ?? null
  const entry = data.recipes.find((recipe) => recipe.dish_uuid === selectedDish)
  const problemStations = data.deliveries.filter((delivery) => delivery.state !== 'applied').length

  return (
    <div className="space-y-5 p-6">
      <StoreCommercialPolicyNotice />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h3 className="text-base font-semibold">Версионные ТТК</h3>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
			Центр утверждает сетевые версии, а станция может предложить новую ТТК и сразу работать
			по ней офлайн. Такие изменения приходят сюда черновиком с номером АЗС. Подтверждённый
			набор доставляется атомарно; блюдо продаётся как сопутствующий товар по НДС 22%.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => query.refetch()} disabled={query.isFetching}>
          <RefreshCw className={query.isFetching ? 'animate-spin' : ''} />Обновить
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard icon={ChefHat} label="Действующие ТТК" value={`${data.summary.active}/${data.summary.recipes}`} hint="на текущую дату" alarm={data.summary.active !== data.summary.recipes} />
        <SummaryCard icon={GitBranch} label="Черновики" value={data.summary.drafts} hint="ещё не влияют на станции" alarm={data.summary.drafts > 0} />
        <SummaryCard icon={PackageCheck} label="Набор" value={shortBundle(data.bundle?.bundle_id)} hint={data.bundle ? `${data.bundle.recipes.length} карт · атомарная доставка` : 'пока не сформирован'} alarm={!data.bundle} />
        <SummaryCard icon={CircleAlert} label="Требуют внимания" value={problemStations} hint={`из ${data.deliveries.length} станций`} alarm={problemStations > 0} />
      </div>

      {data.recipes.length === 0 && data.legacy_available > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-sky-500/30 bg-sky-500/5 p-4">
          <div>
            <div className="text-sm font-medium">Найдены архивные ТТК до перехода</div>
            <div className="text-xs text-muted-foreground">{data.legacy_available} карт можно один раз перенести как действующие версии v1.</div>
          </div>
          <Button onClick={() => bootstrap.mutate()} disabled={!centralWrite || bootstrap.isPending}>Перенести в реестр</Button>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border p-3">
            <span className="text-sm font-medium">Карты</span>
            <Button size="icon-xs" variant="outline" aria-label="Новая ТТК" disabled={!centralWrite}
              onClick={() => setSelected('__new')}><Plus /></Button>
          </div>
          <div className="max-h-[680px] overflow-y-auto p-1.5">
            {data.recipes.map((recipe) => {
              const version = recipe.draft ?? recipe.active
              return (
                <button key={recipe.dish_uuid} onClick={() => setSelected(recipe.dish_uuid)}
                  className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors ${selectedDish === recipe.dish_uuid ? 'bg-primary/10 text-foreground' : 'hover:bg-muted/50'}`}>
                  <div className="truncate text-sm font-medium">{recipe.dish_name}</div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                    <span>{KIND_LABEL[recipe.recipe_kind]}</span>
                    {version && <VersionBadge version={version} />}
                  </div>
                </button>
              )
            })}
            {data.recipes.length === 0 && (
              <div className="p-5 text-center text-xs text-muted-foreground">Версионных ТТК пока нет</div>
            )}
          </div>
        </div>
        <RecipeEditor key={selectedDish ?? 'empty'} entry={entry} createNew={selectedDish === '__new'}
          canWrite={centralWrite} onChanged={(uuid) => setSelected(uuid ?? selectedDish)} />
      </div>

      <div className="rounded-xl border border-border bg-card">
        <div className="border-b border-border p-4">
          <h4 className="font-semibold">Доставка на станции</h4>
          <p className="mt-1 text-xs text-muted-foreground">Применён — агент подтвердил именно текущий центральный набор. Проверка смены приходит отдельным состоянием.</p>
        </div>
        {data.deliveries.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">Агенты станций ещё не выходили на связь.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="px-4 py-2.5 text-left">АЗС</th><th className="px-4 py-2.5 text-left">Доставка</th>
                  <th className="px-4 py-2.5 text-left">Центр / станция</th><th className="px-4 py-2.5 text-left">Проверка смены</th>
                  <th className="px-4 py-2.5 text-left">Последняя связь</th><th className="px-4 py-2.5 text-right">Действие</th>
                </tr>
              </thead>
              <tbody>
                {data.deliveries.map((delivery) => {
                  const readiness = delivery.readiness
                  const блюда = readiness?.dishes ?? []
                  const мешает = блюда.filter((d) => d.state !== 'готово')
                  const раскрыто = открыта === delivery.station_id
                  return (
                    <>
                    <tr key={delivery.station_id} className="border-b border-border last:border-0">
                      <td className="px-4 py-3 font-semibold">{delivery.station_id}</td>
                      <td className="px-4 py-3"><span className={`rounded-full border px-2 py-1 text-xs ${DELIVERY_STYLE[delivery.state]}`}>{DELIVERY_LABEL[delivery.state]}</span></td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{shortBundle(delivery.desired_bundle)} / {shortBundle(delivery.applied_bundle)}</td>
                      <td className="px-4 py-3">
                        {!readiness ? <span className="text-xs text-muted-foreground">нет проверки</span> : readiness.ready
                          ? <span className="inline-flex items-center gap-1.5 text-xs text-emerald-300"><CheckCircle2 className="h-4 w-4" />готово</span>
                          : <span className="inline-flex items-center gap-1.5 text-xs text-red-300" title={readiness.issues?.map((issue) => issue.message).join('\n')}><CircleAlert className="h-4 w-4" />{readiness.critical ?? 0} крит.</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground"><span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" />{localDate(delivery.agent_last_seen)}</span></td>
                      <td className="px-4 py-3 text-right"><Button size="xs" variant="outline" onClick={() => push.mutate(delivery.station_id)} disabled={!centralWrite || !data.bundle || push.isPending}><Send />Отправить</Button></td>
                    </tr>
                    {раскрыто && мешает.length > 0 && (
                      <tr key={`${delivery.station_id}-детали`} className="border-b border-border bg-muted/20">
                        <td colSpan={6} className="px-4 py-3">
                          <div className="mb-2 text-xs text-muted-foreground">
                            Причины разной природы и чинят их разные люди: цену назначает администратор АЗС,
                            код кассы закрепляется на станции, канон штрихкода и ставки ведёт товаровед сети,
                            сырьё надо заказать. «Без прихода» продажу не блокирует — там
                            неверны себестоимость и остаток.
                          </div>
                          <table className="w-full text-xs">
                            <tbody>
                              {мешает.map((d) => (
                                <tr key={d.name} className="border-t border-border/30">
                                  <td className="py-1.5 pr-3">{d.name}</td>
                                  <td className="py-1.5 pr-3 whitespace-nowrap">
                                    <span className={d.state === 'стоп' ? 'text-red-300' : 'text-amber-300/90'}>
                                      {d.state}
                                    </span>
                                  </td>
                                  <td className="py-1.5 pr-3 text-muted-foreground">
                                    {(d.reasons ?? []).join(' · ') || '—'}
                                  </td>
                                  <td className="py-1.5 text-muted-foreground/80">
                                    {(d.owners ?? []).join(' · ')}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                    </>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
