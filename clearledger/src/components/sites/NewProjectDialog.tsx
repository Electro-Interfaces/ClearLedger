/**
 * Заведение проекта руками — площадка приходит не только файлом, но и звонком.
 *
 * Форма намеренно короткая: на входе известны адрес и от кого пришло, всё
 * остальное добывается по ходу и заполняется в карточке. Проект создаётся
 * стадией «Лид» и сразу получает номер.
 */
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ProjectSuggestInput } from './ProjectSuggestInput'
import { PROJECT_OBJECT_TYPES, type ProjectSuggestionField } from '@/services/sitesService'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { createSite, getProjectKinds, getSites } from '@/services/sitesService'
import { useOpenProject } from './useOpenProject'

export function NewProjectDialog({ companyId, onClose, onCreated }: {
  companyId: string; onClose: () => void; onCreated: (id: string) => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    title: '', region: '', city: '', address: '', place_kind: '', install_place: '', owner: '',
  })
  // Вид работы — ось маршрута: по нему процесс на входе решает, вести ли подбор
  // земли и договор или сразу планировать работы. Спросить потом уже поздно:
  // проект успеет уехать по чужой ветке.
  const [kind, setKind] = useState('new_build')
  const kinds = useQuery({ queryKey: ['pr-kinds', companyId], queryFn: () => getProjectKinds(companyId) })
  const kindDef = (kinds.data?.kinds ?? []).find((k) => k.key === kind)
  const [busy, setBusy] = useState(false)
  // Место должно быть опознаваемо: без адреса или названия объекта проект
  // невозможно ни найти, ни отличить от соседнего.
  const canSave = Boolean(form.address.trim() || form.install_place.trim())

  // Подсказка о дубле. Место занимается один раз, а проектов по нему заводят
  // несколько: отказ уезжает в архив, через полгода адрес приходит снова и
  // проект заводится заново — вместе со второй историей согласований. Ищем по
  // ВСЕМ стадиям, включая архив: именно там лежит то, что человек не увидит в
  // реестре. Запрета нет намеренно — адрес часто известен до города, и запрет
  // по совпадению остановил бы обычную работу.
  const openProject = useOpenProject()
  const probe = (form.address.trim() || form.install_place.trim()).trim()
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebounced(probe.length >= 4 ? probe : ''), 400)
    return () => clearTimeout(t)
  }, [probe])
  const similar = useQuery({
    queryKey: ['pr-duplicates', companyId, debounced],
    queryFn: () => getSites({ companyId, search: debounced, pageSize: 5 }),
    enabled: debounced.length >= 4,
  })
  const duplicates = similar.data?.items ?? []

  const save = async () => {
    setBusy(true)
    try {
      // Стадию старта берём у вида: переносу и демонтажу подбор локации не нужен.
      const s = await createSite(companyId, { ...form, kind, stage: kindDef?.startStage ?? 'lead' })
      await qc.invalidateQueries({ queryKey: ['pr-projects', companyId] })
      await qc.invalidateQueries({ queryKey: ['pr-board', companyId] })
      await qc.invalidateQueries({ queryKey: ['pr-suggestions', companyId] })
      await qc.invalidateQueries({ queryKey: ['pr-portfolio', companyId] })
      await qc.invalidateQueries({ queryKey: ['sites-list', companyId] })
      await qc.invalidateQueries({ queryKey: ['sites-overview', companyId] })
      toast.success(`Проект ${s.projectNo ?? ''} заведён`)
      onCreated(s.id)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось создать проект')
    } finally { setBusy(false) }
  }

  const field = (k: keyof typeof form, label: string, ph?: string) => (
    <div>
      <label htmlFor={`project-${k}`} className="block text-xs uppercase tracking-wide text-muted-foreground mb-0.5">{label}</label>
      <Input id={`project-${k}`} className="h-9 text-sm" value={form[k]} placeholder={ph}
        onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
    </div>
  )

  const change = (key: ProjectSuggestionField, value: string) => setForm((current) => ({
    ...current, [key]: value,
    ...(key === 'region' ? { city: '', address: '' } : key === 'city' ? { address: '' } : {}),
  }))
  const suggestField = (key: ProjectSuggestionField, label: string, placeholder: string) => (
    <ProjectSuggestInput companyId={companyId} field={key} label={label} value={form[key]} placeholder={placeholder}
      region={key === 'city' || key === 'address' ? form.region : undefined}
      city={key === 'address' ? form.city : undefined} onChange={(value) => change(key, value)}
      onSelect={(item) => setForm((current) => ({ ...current,
        ...(key === 'region' ? { city: '', address: '' } : key === 'city' ? { address: '' } : {}),
        ...item.fields, [key]: item.value,
      }))} />
  )

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg w-[92vw] max-h-[90dvh] overflow-y-auto">
        <DialogHeader><DialogTitle className="text-base">Новый проект</DialogTitle>
          <DialogDescription>Укажите вид работ и место. Остальные данные можно заполнить позже.</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Номер присваивается автоматически. Документы и детали можно добавить в карточке проекта.
          </p>
          <div>
            <label htmlFor="project-kind" className="block text-xs uppercase tracking-wide text-muted-foreground mb-0.5">Вид работ</label>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger id="project-kind" className="h-9 w-full text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(kinds.data?.kinds ?? []).map((k) => (
                  <SelectItem key={k.key} value={k.key} className="text-sm">{k.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {kindDef && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {/* Подсказка вида — обрывок фразы («площадка становится станцией»):
                    в справочнике она задумана как продолжение названия. Без него
                    строка начинается со строчной буквы и читается как ошибка. */}
                {kindDef.label} — {kindDef.hint}.
              </p>
            )}
          </div>
          {suggestField('title', 'Название проекта', 'ЭЗС на парковке ТЦ «Гринвич»')}
          <div className="grid grid-cols-2 gap-2">
            {suggestField('region', 'Регион', 'Свердловская область')}
            {suggestField('city', 'Город', 'Екатеринбург')}
          </div>
          {suggestField('address', 'Адрес', 'ул. Кирова, 12')}
          <div>
            <label htmlFor="project-object-type" className="block text-xs uppercase tracking-wide text-muted-foreground mb-1">Тип объекта</label>
            <Select value={form.place_kind || '__none__'} onValueChange={(value) => setForm((current) => ({ ...current, place_kind: value === '__none__' ? '' : value }))}>
              <SelectTrigger id="project-object-type" className="h-9 w-full text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">Не указан</SelectItem>
                {PROJECT_OBJECT_TYPES.map((label) => <SelectItem key={label} value={label.toLocaleLowerCase('ru')}>{label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {suggestField('install_place', 'Место установки', 'ТЦ «Гринвич», парковка')}
          {field('owner', 'Собственник', 'если известен')}
          {!canSave && (
            <p className="text-xs text-muted-foreground">
              Нужен адрес или место установки — иначе проект не отличить от соседнего.
            </p>
          )}
          {duplicates.length > 0 && (
            <div className="border border-amber-500/40 bg-amber-500/[0.06] rounded-md px-2.5 py-2 space-y-1.5">
              <div className="text-xs font-medium">
                Похожее место уже заводили — {duplicates.length === 5 ? 'нашлось не меньше пяти' : `нашлось ${duplicates.length}`}
              </div>
              {duplicates.map((d) => (
                <button key={d.id} type="button"
                  onClick={() => { onClose(); openProject(d.id) }}
                  className="w-full text-left text-xs rounded px-1.5 py-1 hover:bg-accent/60">
                  <span className="font-medium">{d.projectNo ?? 'без номера'}</span>
                  {' · '}{d.address ?? d.installPlace ?? d.title ?? d.city ?? 'без адреса'}
                  {' · '}<span className="text-muted-foreground">{d.stageLabel}</span>
                  {d.archiveReason ? <span className="text-muted-foreground"> ({d.archiveReason})</span> : null}
                </button>
              ))}
              <p className="text-[11px] text-muted-foreground">
                Закрытый проект лучше вернуть в работу из его карточки, чем заводить
                заново: с новым потеряется прежняя переписка и согласования.
              </p>
            </div>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" className="h-8 text-sm" onClick={onClose}>Отмена</Button>
            <Button size="sm" className="h-8 text-sm" disabled={!canSave || busy} onClick={save}>
              {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}Создать
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
