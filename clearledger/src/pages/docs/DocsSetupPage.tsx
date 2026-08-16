/**
 * Настройка «Трека»: виды документов и нумераторы.
 *
 * Вид несёт правило нумерации, поэтому правит его администратор пространства:
 * номер стоит в документе и потом не переписывается.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { Button } from '@/components/ui/button'
import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'
import * as docsService from '@/services/docsService'
import * as tasksService from '@/services/tasksService'
import { DOC_FAMILY } from '@/services/docsService'
import { useDocsView } from './DocsLayout'

const SCOPE_LABEL: Record<string, string> = {
  kind: 'сквозная по виду',
  kind_year: 'по виду и году',
  kind_org: 'по виду и юрлицу',
  kind_org_year: 'по виду, юрлицу и году',
}

export function DocsSetupPage() {
  const { company } = useCompany()
  const qc = useQueryClient()
  const view = useDocsView('/docs/setup')
  const companyId = company?.id ?? ''

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

  if (view === 'substitutions') {
    return <Substitutions companyId={companyId} />
  }

  if (view === 'exchange') {
    return <ExchangeTargets companyId={companyId} />
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
        <Button size="sm" variant="outline" onClick={() => starter.mutate()}
          disabled={starter.isPending}>
          Завести обычный набор
        </Button>
      </div>

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
            <span className="font-mono text-xs text-muted-foreground">{k.code}</span>
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
              <Button size="sm" variant="ghost" onClick={() => stop.mutate(r.id)}
                disabled={stop.isPending}>
                Прекратить
              </Button>
            )}
          </div>
        ))}
        {rows.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Замещений нет
          </div>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <div className="text-sm font-medium">Новое замещение</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">Кого замещают</Label>
            <select value={form.user_id}
              onChange={(e) => setForm({ ...form, user_id: e.target.value })}
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
              <option value="">выберите</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Кто замещает</Label>
            <select value={form.deputy_id}
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
          disabled={!form.user_id || !form.deputy_id || !form.starts_on
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
              <Label htmlFor={`scan-${t.id}`} className="text-xs text-muted-foreground">
                Интервал, минут
              </Label>
              <Input id={`scan-${t.id}`} type="number" min={5} max={1440}
                value={intervals[t.id] ?? String(t.scan_interval_min)}
                onChange={(e) => setIntervals((current) => ({
                  ...current, [t.id]: e.target.value,
                }))} className="h-8 w-24" />
              <Button size="sm" variant="outline" disabled={schedule.isPending
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
        {targets.length === 0 && (
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
            placeholder="/mnt/sedo/out" />
          <Field label="Папка приёма" value={form.inbox_path}
            onChange={(v) => setForm({ ...form, inbox_path: v })}
            placeholder="/mnt/sedo/in" />
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
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Input type={type} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder} className="h-9" />
    </div>
  )
}

export default DocsSetupPage
