/**
 * Настройка «Трека»: виды документов и нумераторы.
 *
 * Вид несёт правило нумерации, поэтому правит его администратор пространства:
 * номер стоит в документе и потом не переписывается.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { useId, useState } from 'react'
import { Card } from '@/components/ui/card'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { ConfirmActionDialog } from '@/components/common/ConfirmActionDialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import * as docsService from '@/services/docsService'
import * as tasksService from '@/services/tasksService'
import { DOC_FAMILY } from '@/services/docsService'
import { useDocsView } from './DocsLayout'
import { DocKindEditor } from '@/components/docs/DocKindEditor'

const SCOPE_LABEL: Record<string, string> = {
  kind: 'сквозная по виду',
  kind_year: 'по виду и году',
  kind_org: 'по виду и юрлицу',
  kind_org_year: 'по виду, юрлицу и году',
}

export function DocsSetupPage() {
  const { company, isCompanyAdmin } = useCompany()
  const qc = useQueryClient()
  const view = useDocsView('/docs/setup')
  const companyId = company?.id ?? ''
  const [editingKindId, setEditingKindId] = useState<string | 'new' | null>(null)

  const kindsQ = useQuery({
    queryKey: ['doc-kinds', companyId],
    queryFn: () => docsService.listKinds(companyId),
    enabled: !!companyId,
  })

  const starter = useMutation({
    mutationFn: () => docsService.starterKinds(companyId),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['doc-kinds', companyId] })
      toast.success(r.added ? `Заведено видов: ${r.added}` : 'Всё уже заведено')
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const kinds = kindsQ.data ?? []
  const editingKind = editingKindId === 'new'
    ? undefined : kinds.find((kind) => kind.id === editingKindId)

  if (!isCompanyAdmin) {
    return (
      <div className="px-4 py-4">
        <Card className="p-5 text-sm text-muted-foreground">
          Настройку видов, нумераторов, обмена и замещений ведёт администратор пространства.
        </Card>
      </div>
    )
  }

  if (view === 'substitutions') {
    return <Substitutions companyId={companyId} />
  }

  if (view === 'exchange') {
    return <ExchangeTargets companyId={companyId} />
  }

  if (view === 'cases') {
    return <Cases companyId={companyId} />
  }

  if (view === 'labels') {
    return <Labels companyId={companyId} />
  }

  if ((view === 'kinds' || view === 'counters') && kindsQ.isLoading) {
    return (
      <div className="px-4 py-4">
        <Card className="p-6 text-sm text-muted-foreground" role="status" aria-live="polite">
          Загружаем виды документов…
        </Card>
      </div>
    )
  }

  if ((view === 'kinds' || view === 'counters') && kindsQ.isError) {
    return (
      <div className="px-4 py-4">
        <Card role="alert" className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <div className="text-sm font-medium">Виды документов не загрузились</div>
            <div className="text-xs text-muted-foreground">
              Справочник не заменён пустым списком. Нумерацию и виды пока нельзя менять.
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => kindsQ.refetch()}>Повторить</Button>
        </Card>
      </div>
    )
  }

  if (view === 'counters') {
    return (
      <div className="space-y-3 px-4 py-4">
        <div>
          <h1 className="text-base font-semibold">Нумераторы</h1>
          <p className="text-xs text-muted-foreground">
            Область нумерации задаётся видом документа. Счётчик транзакционный:
            отменённая регистрация возвращает номер, поэтому пропусков в журнале нет.
          </p>
        </div>
        <Card className="divide-y divide-border/60">
          {kinds.map((k) => (
            <div key={k.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <div>
                <div className="text-sm font-medium">{k.name}</div>
                <div className="text-[11px] text-muted-foreground">
                  {k.number_template.replace('{prefix}', k.number_prefix || k.code)}
                  {' · '}{SCOPE_LABEL[k.number_scope] ?? k.number_scope}
                </div>
              </div>
              <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs">
                {k.number_prefix || '—'}
              </span>
            </div>
          ))}
          {kinds.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              Видов документов пока нет
            </div>
          )}
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-3 px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold">Виды документов</h1>
          <p className="text-xs text-muted-foreground">
            Вид задаёт поток, правило нумерации и то, каким типом ставится поручение
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setEditingKindId('new')}>
            <Plus className="mr-1 h-4 w-4" />Новый вид
          </Button>
          <Button size="sm" variant="outline" onClick={() => starter.mutate()}
            disabled={starter.isPending}>
            Завести обычный набор
          </Button>
        </div>
      </div>

      {editingKindId && (
        <DocKindEditor key={editingKindId} companyId={companyId} initial={editingKind}
          onClose={() => setEditingKindId(null)} onSaved={() => setEditingKindId(null)} />
      )}

      <Card className="divide-y divide-border/60">
        {kinds.map((k) => (
          <div key={k.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-sm font-medium">{k.name}</div>
              <div className="text-[11px] text-muted-foreground">
                {DOC_FAMILY[k.family] ?? k.family}
                {' · номер '}
                {k.number_template.replace('{prefix}', k.number_prefix || k.code)}
                {' · '}{SCOPE_LABEL[k.number_scope] ?? k.number_scope}
              </div>
              {k.description && (
                <div className="pt-0.5 text-[11px] text-muted-foreground">{k.description}</div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">{k.code}</span>
              <Button type="button" size="sm" variant="ghost" onClick={() => setEditingKindId(k.id)}>
                <Pencil className="mr-1 h-3.5 w-3.5" />Изменить
              </Button>
            </div>
          </div>
        ))}
        {kinds.length === 0 && (
          <div className="px-3 py-8 text-center text-sm text-muted-foreground">
            Видов пока нет. Обычный набор — входящее и исходящее письмо, приказ,
            служебная записка.
          </div>
        )}
      </Card>
    </div>
  )
}

const LABEL_COLORS = [
  { value: 'slate', label: 'Серый', className: 'bg-slate-500' },
  { value: 'blue', label: 'Синий', className: 'bg-blue-500' },
  { value: 'green', label: 'Зелёный', className: 'bg-emerald-500' },
  { value: 'amber', label: 'Жёлтый', className: 'bg-amber-500' },
  { value: 'red', label: 'Красный', className: 'bg-red-500' },
] as const

function Labels({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [color, setColor] = useState('slate')
  const labelsQ = useQuery({
    queryKey: ['doc-labels', companyId],
    queryFn: () => docsService.listDocLabels(companyId),
    enabled: !!companyId,
  })
  const create = useMutation({
    mutationFn: () => docsService.createDocLabel(companyId, name.trim(), color),
    onSuccess: () => {
      toast.success('Метка добавлена')
      setName('')
      qc.invalidateQueries({ queryKey: ['doc-labels', companyId] })
      qc.invalidateQueries({ queryKey: ['task-labels', companyId] })
    },
    onError: () => toast.error('Не удалось добавить метку. Повторите попытку.'),
  })
  const remove = useMutation({
    mutationFn: (id: string) => docsService.deleteDocLabel(companyId, id),
    onSuccess: () => {
      toast.success('Метка удалена из документов и поручений')
      qc.invalidateQueries({ queryKey: ['doc-labels', companyId] })
      qc.invalidateQueries({ queryKey: ['task-labels', companyId] })
    },
    onError: () => toast.error('Не удалось удалить метку. Повторите попытку.'),
  })
  const labels = labelsQ.data?.labels ?? []

  return (
    <div className="space-y-3 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Метки</h1>
        <p className="text-xs text-muted-foreground">
          Справочник общий для документов и поручений: одинаковая метка означает одно и то же.
        </p>
      </div>

      {labelsQ.isError && (
        <Card role="alert" className="flex flex-wrap items-center justify-between gap-3 p-4">
          <span className="text-sm">Метки не загрузились. Справочник не изменён.</span>
          <Button size="sm" variant="outline" onClick={() => labelsQ.refetch()}>Повторить</Button>
        </Card>
      )}

      {!labelsQ.isError && (
        <Card className="divide-y divide-border/60">
          {labelsQ.isLoading && (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">Загрузка меток…</div>
          )}
          {labels.map((label) => {
            const tone = LABEL_COLORS.find((item) => item.value === label.color)
              ?? LABEL_COLORS[0]
            return (
              <div key={label.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
                  <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${tone.className}`}
                    aria-hidden="true" />
                  <span className="truncate">{label.name}</span>
                  <span className="sr-only">Цвет: {tone.label}</span>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button size="sm" variant="ghost" aria-label={`Удалить метку «${label.name}»`}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Удалить метку «{label.name}»?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Она будет снята со всех документов и поручений. История самих объектов сохранится.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Не удалять</AlertDialogCancel>
                      <AlertDialogAction onClick={() => remove.mutate(label.id)}>
                        Удалить метку
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            )
          })}
          {labelsQ.isSuccess && labels.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">Меток пока нет</div>
          )}
        </Card>
      )}

      <Card className="space-y-3 p-4">
        <div className="text-sm font-medium">Новая метка</div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-56 flex-1 space-y-1">
            <Label htmlFor="doc-label-name" className="text-xs">Название</Label>
            <Input id="doc-label-name" value={name}
              onChange={(event) => setName(event.target.value)} maxLength={60}
              placeholder="Например, особый контроль" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="doc-label-color" className="text-xs">Цвет</Label>
            <select id="doc-label-color" value={color}
              onChange={(event) => setColor(event.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm">
              {LABEL_COLORS.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </div>
          <Button size="sm" disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}>
            Добавить
          </Button>
        </div>
      </Card>
    </div>
  )
}

function Cases({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const { organizations } = useCompany()
  const currentYear = new Date().getFullYear()
  const [form, setForm] = useState({
    year: String(currentYear), index: '', title: '', storage_term: '5 лет',
    storage_years: '5', organization_id: '', epk: false,
  })

  const rowsQ = useQuery({
    queryKey: ['doc-cases', companyId],
    queryFn: () => docsService.listCases(companyId),
    enabled: !!companyId,
  })
  const create = useMutation({
    mutationFn: () => docsService.createCase(companyId, {
      year: Number(form.year), index: form.index.trim(), title: form.title.trim(),
      storage_term: form.storage_term.trim(),
      storage_years: form.storage_years === '' ? null : Number(form.storage_years),
      organization_id: form.organization_id || null, epk: form.epk,
    }),
    onSuccess: () => {
      toast.success('Дело заведено')
      setForm((current) => ({ ...current, index: '', title: '' }))
      qc.invalidateQueries({ queryKey: ['doc-cases', companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const close = useMutation({
    mutationFn: (caseId: string) => docsService.closeCase(companyId, caseId),
    onSuccess: () => {
      toast.success('Дело закрыто для новых документов')
      qc.invalidateQueries({ queryKey: ['doc-cases', companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const rollover = useMutation({
    mutationFn: () => docsService.rolloverCases(companyId, currentYear + 1),
    onSuccess: (result) => {
      toast.success(
        `На ${currentYear + 1} год: новых дел ${result.added}, видов обновлено ${result.defaults_updated}`,
      )
      qc.invalidateQueries({ queryKey: ['doc-cases', companyId] })
      qc.invalidateQueries({ queryKey: ['doc-kinds', companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const rows = rowsQ.data ?? []
  const organizationName = new Map(organizations.map((item) => [item.id, item.name]))
  const year = Number(form.year)
  const storageYears = form.storage_years === '' ? null : Number(form.storage_years)
  const valid = Number.isInteger(year) && year >= 2000 && year <= 2100
    && (storageYears === null || (Number.isInteger(storageYears)
      && storageYears >= 0 && storageYears <= 100))
    && !!form.index.trim() && !!form.title.trim() && !!form.storage_term.trim()

  return (
    <div className="space-y-3 px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold">Номенклатура дел</h1>
          <p className="text-xs text-muted-foreground">
            Закрытое дело остаётся в истории, но больше не принимает документы.
          </p>
        </div>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button size="sm" variant="outline" disabled={rollover.isPending}>
              Создать дела на {currentYear + 1}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Перенести номенклатуру на {currentYear + 1} год?</AlertDialogTitle>
              <AlertDialogDescription>
                Открытые дела будут скопированы, а виды документов переключены на новые дела.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Отмена</AlertDialogCancel>
              <AlertDialogAction onClick={() => rollover.mutate()}>
                Создать номенклатуру
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
      {rowsQ.isError && (
        <Card role="alert" className="flex items-center justify-between gap-3 border-destructive/30 p-3 text-sm">
          <span>Номенклатура не загрузилась. Подшивка документов временно недоступна.</span>
          <Button size="sm" variant="outline" onClick={() => rowsQ.refetch()}>Повторить</Button>
        </Card>
      )}
      <Card className="divide-y divide-border/60">
        {rowsQ.isLoading && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">Загрузка замещений…</div>
        )}
        {rowsQ.isError && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 px-3 py-4">
            <span className="text-sm">Замещения не загрузились</span>
            <Button size="sm" variant="outline" onClick={() => rowsQ.refetch()}>Повторить</Button>
          </div>
        )}
        {rowsQ.isLoading && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">Загрузка дел…</div>
        )}
        {rows.map((item) => (
          <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-sm font-medium">{item.year} · {item.index} · {item.title}</div>
              <div className="text-[11px] text-muted-foreground">
                {item.storage_term}{item.epk ? ' · ЭПК' : ''}
                {item.organization_id
                  ? ` · ${organizationName.get(item.organization_id) ?? 'юрлицо'}` : ' · вся компания'}
                {item.status === 'closed' ? ' · закрыто' : ''}
              </div>
            </div>
            {item.status === 'open' && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="sm" variant="ghost" disabled={close.isPending}>
                    Закрыть дело
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Закрыть дело {item.index}?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Оно останется в истории, но новые документы подшить в него будет нельзя.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Не закрывать</AlertDialogCancel>
                    <AlertDialogAction onClick={() => close.mutate(item.id)}>
                      Закрыть дело
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
        ))}
        {rowsQ.isSuccess && rows.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">Дел пока нет</div>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <div className="text-sm font-medium">Новое дело</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Год" value={form.year}
            onChange={(value) => setForm({ ...form, year: value })} type="number" />
          <Field label="Индекс" value={form.index}
            onChange={(value) => setForm({ ...form, index: value })} placeholder="01-15" />
          <div className="sm:col-span-2">
            <Field label="Название" value={form.title}
              onChange={(value) => setForm({ ...form, title: value })}
              placeholder="Переписка по основной деятельности" />
          </div>
          <Field label="Срок хранения" value={form.storage_term}
            onChange={(value) => setForm({ ...form, storage_term: value })} />
          <Field label="Лет (пусто — постоянно)" value={form.storage_years}
            onChange={(value) => setForm({ ...form, storage_years: value })} type="number" />
          <div className="space-y-1">
            <Label htmlFor="case-organization" className="text-xs">Юрлицо</Label>
            <select id="case-organization" value={form.organization_id}
              onChange={(event) => setForm({ ...form, organization_id: event.target.value })}
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
              <option value="">Вся компания</option>
              {organizations.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </div>
          <label className="flex h-9 items-center gap-2 self-end text-sm">
            <input type="checkbox" checked={form.epk}
              onChange={(event) => setForm({ ...form, epk: event.target.checked })} />
            Экспертная комиссия
          </label>
        </div>
        <Button size="sm" disabled={!valid || create.isPending}
          onClick={() => create.mutate()}>
          Завести дело
        </Button>
      </Card>
    </div>
  )
}

function Substitutions({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    user_id: '', deputy_id: '', starts_on: '', ends_on: '', basis: '',
  })

  const rowsQ = useQuery({
    queryKey: ['doc-substitutions', companyId],
    queryFn: () => docsService.listSubstitutions(companyId),
    enabled: !!companyId,
  })
  const peopleQ = useQuery({
    queryKey: ['task-people', companyId],
    queryFn: () => tasksService.listTaskPeople(companyId),
    staleTime: 5 * 60 * 1000,
  })

  const create = useMutation({
    mutationFn: () => docsService.createSubstitution(companyId, form),
    onSuccess: () => {
      toast.success('Замещение назначено')
      setForm({ user_id: '', deputy_id: '', starts_on: '', ends_on: '', basis: '' })
      qc.invalidateQueries({ queryKey: ['doc-substitutions', companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const stop = useMutation({
    mutationFn: (id: string) => docsService.stopSubstitution(companyId, id),
    onSuccess: () => {
      toast.success('Замещение прекращено')
      qc.invalidateQueries({ queryKey: ['doc-substitutions', companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const rows = rowsQ.data ?? []
  const people = peopleQ.data?.people ?? []

  return (
    <div className="space-y-3 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Замещения</h1>
        <p className="text-xs text-muted-foreground">
          Визу за другого поставить нельзя - это подделка согласования. Но отпуск
          не должен останавливать документ: заместитель визирует от своего имени,
          и в листе видно обоих.
        </p>
      </div>

      <Card className="divide-y divide-border/60">
        {rows.map((r) => (
          <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-sm">
                {r.deputy} <span className="text-muted-foreground">замещает</span> {r.user}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {r.starts_on} - {r.ends_on}
                {r.basis ? ` · ${r.basis}` : ''}
                {r.now ? ' · действует сейчас' : ''}
                {!r.is_active ? ' · прекращено' : ''}
              </div>
            </div>
            {r.is_active && (
              <ConfirmActionDialog
                trigger={(
                  <Button size="sm" variant="ghost" disabled={stop.isPending}>
                    Прекратить
                  </Button>
                )}
                title="Прекратить замещение?"
                description={`${r.deputy} больше не сможет принимать решения за ${r.user}. Уже поставленные визы останутся в истории от имени заместителя.`}
                confirmLabel="Прекратить"
                destructive
                pending={stop.isPending}
                onConfirm={() => stop.mutateAsync(r.id)}
              />
            )}
          </div>
        ))}
        {rowsQ.isSuccess && rows.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Замещений нет
          </div>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <div className="text-sm font-medium">Новое замещение</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {peopleQ.isLoading && (
            <div className="sm:col-span-2 text-sm text-muted-foreground" role="status">
              Загружаем сотрудников…
            </div>
          )}
          {peopleQ.isError && (
            <div role="alert" className="flex flex-wrap items-center justify-between gap-3 sm:col-span-2">
              <span className="text-sm text-destructive">Сотрудники не загрузились</span>
              <Button size="sm" variant="outline" onClick={() => peopleQ.refetch()}>Повторить</Button>
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="substitution-user" className="text-xs">Кого замещают</Label>
            <select id="substitution-user" value={form.user_id} disabled={!peopleQ.isSuccess}
              onChange={(e) => setForm({ ...form, user_id: e.target.value })}
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
              <option value="">выберите</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="substitution-deputy" className="text-xs">Кто замещает</Label>
            <select id="substitution-deputy" value={form.deputy_id} disabled={!peopleQ.isSuccess}
              onChange={(e) => setForm({ ...form, deputy_id: e.target.value })}
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
              <option value="">выберите</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <Field label="С какой даты" value={form.starts_on}
            onChange={(v) => setForm({ ...form, starts_on: v })} type="date" />
          <Field label="По какую дату" value={form.ends_on}
            onChange={(v) => setForm({ ...form, ends_on: v })} type="date" />
          <div className="sm:col-span-2">
            <Field label="Основание" value={form.basis}
              onChange={(v) => setForm({ ...form, basis: v })}
              placeholder="Приказ №12 от 14.08.2026 о возложении обязанностей" />
          </div>
        </div>
        <Button size="sm" onClick={() => create.mutate()}
          disabled={!peopleQ.isSuccess || !form.user_id || !form.deputy_id || !form.starts_on
            || !form.ends_on || create.isPending}>
          Назначить
        </Button>
      </Card>
    </div>
  )
}

function ExchangeTargets({ companyId }: { companyId: string }) {
  const qc = useQueryClient()
  const [intervals, setIntervals] = useState<Record<string, string>>({})
  const [form, setForm] = useState({
    code: '', name: '', system: 'sedo', outbox_path: '', inbox_path: '',
  })

  const targetsQ = useQuery({
    queryKey: ['doc-exchange-targets', companyId],
    queryFn: () => docsService.exchangeTargets(companyId),
    enabled: !!companyId,
  })

  const create = useMutation({
    mutationFn: () => docsService.createExchangeTarget(companyId, form),
    onSuccess: () => {
      toast.success('Точка обмена заведена')
      setForm({ code: '', name: '', system: 'sedo', outbox_path: '', inbox_path: '' })
      qc.invalidateQueries({ queryKey: ['doc-exchange-targets', companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const schedule = useMutation({
    mutationFn: ({ id, enabled, interval }: { id: string; enabled: boolean; interval: number }) =>
      docsService.updateExchangeSchedule(companyId, id, enabled, interval),
    onSuccess: () => {
      toast.success('Расписание сохранено')
      qc.invalidateQueries({ queryKey: ['doc-exchange-targets', companyId] })
    },
    onError: (e) => toast.error((e as Error).message),
  })
  const scan = useMutation({
    mutationFn: (id: string) => docsService.scanInbox(companyId, id),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['doc-exchange-targets', companyId] })
      if (result.errors.length) toast.error(result.errors[0].error)
      else toast.success(result.added ? `Новых файлов: ${result.added}` : 'Папка проверена, новых файлов нет')
    },
    onError: (error) => toast.error((error as Error).message),
  })

  const targets = targetsQ.data ?? []
  const intervalFor = (target: docsService.DocExchangeTarget) =>
    Number(intervals[target.id] ?? target.scan_interval_min)

  return (
    <div className="space-y-3 px-4 py-4">
      <div>
        <h1 className="text-base font-semibold">Обмен с корпоративными системами</h1>
        <p className="text-xs text-muted-foreground">
          Обмен идёт папками: согласованный документ кладётся пакетом в папку СЭД,
          оттуда его забирает головная компания. Обратно так же.
        </p>
      </div>

      <Card className="divide-y divide-border/60">
        {targetsQ.isLoading && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">Загрузка точек обмена…</div>
        )}
        {targetsQ.isError && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 px-3 py-4">
            <span className="text-sm text-destructive">Точки обмена не загрузились</span>
            <Button size="sm" variant="outline" onClick={() => targetsQ.refetch()}>Повторить</Button>
          </div>
        )}
        {targets.map((t) => (
          <div key={t.id} className="px-3 py-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-medium">{t.name}</div>
              <span className="font-mono text-xs text-muted-foreground">{t.code}</span>
            </div>
            <div className="text-[11px] text-muted-foreground">
              выгрузка: {t.outbox_path || 'не указана'}
            </div>
            <div className="text-[11px] text-muted-foreground">
              приём: {t.inbox_path || 'не указан'}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" disabled={scan.isPending || !t.is_active
                || !t.inbox_configured} onClick={() => scan.mutate(t.id)}>
                Проверить сейчас
              </Button>
              <Label htmlFor={`scan-${t.id}`} className="text-xs text-muted-foreground">
                Интервал, минут
              </Label>
              <Input id={`scan-${t.id}`} type="number" min={5} max={1440}
                value={intervals[t.id] ?? String(t.scan_interval_min)}
                onChange={(e) => setIntervals((current) => ({
                  ...current, [t.id]: e.target.value,
                }))} className="h-8 w-24" />
              <Button size="sm" variant="outline" disabled={schedule.isPending || !t.is_active
                || !Number.isInteger(intervalFor(t))
                || intervalFor(t) < 5 || intervalFor(t) > 1440}
                onClick={() => schedule.mutate({
                  id: t.id, enabled: true,
                  interval: intervalFor(t),
                })}>
                {t.scan_enabled ? 'Сохранить интервал' : 'Включить автопроверку'}
              </Button>
              {t.scan_enabled && (
                <Button size="sm" variant="ghost" disabled={schedule.isPending}
                  onClick={() => schedule.mutate({
                    id: t.id, enabled: false, interval: t.scan_interval_min,
                  })}>
                  Отключить
                </Button>
              )}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {t.scan_enabled ? 'Автопроверка включена' : 'Автопроверка выключена'}
              {t.last_scan_at ? ` · последняя ${t.last_scan_at.slice(0, 16).replace('T', ' ')}` : ''}
            </div>
            {t.last_error && (
              <div className="text-[11px] text-destructive">ошибка: {t.last_error}</div>
            )}
          </div>
        ))}
        {targetsQ.isSuccess && targets.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Точек обмена нет. Пакет всё равно можно забрать кнопкой «Скачать пакет»
            в карточке документа.
          </div>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <div className="text-sm font-medium">Новая точка</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Код" value={form.code}
            onChange={(v) => setForm({ ...form, code: v })} placeholder="sedo" />
          <Field label="Название" value={form.name}
            onChange={(v) => setForm({ ...form, name: v })}
            placeholder="СЭД головной компании" />
          <Field label="Папка выгрузки" value={form.outbox_path}
            onChange={(v) => setForm({ ...form, outbox_path: v })}
            placeholder={`/exchange/${companyId}/out`} />
          <Field label="Папка приёма" value={form.inbox_path}
            onChange={(v) => setForm({ ...form, inbox_path: v })}
            placeholder={`/exchange/${companyId}/in`} />
        </div>
        <Button size="sm" onClick={() => create.mutate()}
          disabled={!form.code.trim() || !form.name.trim() || create.isPending}>
          Завести
        </Button>
      </Card>
    </div>
  )
}

function Field({ label, value, onChange, placeholder, type }: {
  label: string; value: string; onChange: (v: string) => void
  placeholder?: string; type?: string
}) {
  const controlId = useId()
  return (
    <div className="space-y-1">
      <Label htmlFor={controlId} className="text-xs">{label}</Label>
      <Input id={controlId} type={type} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder} className="h-9" />
    </div>
  )
}

export default DocsSetupPage
