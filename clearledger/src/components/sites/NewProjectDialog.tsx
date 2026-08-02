/**
 * Заведение проекта руками — площадка приходит не только файлом, но и звонком.
 *
 * Форма намеренно короткая: на входе известны адрес и от кого пришло, всё
 * остальное добывается по ходу и заполняется в карточке. Проект создаётся
 * стадией «Лид» и сразу получает номер.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { createSite, getProjectKinds } from '@/services/sitesService'

export function NewProjectDialog({ companyId, onClose, onCreated }: {
  companyId: string; onClose: () => void; onCreated: (id: string) => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    title: '', region: '', city: '', address: '', install_place: '', owner: '',
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

  const save = async () => {
    setBusy(true)
    try {
      // Стадию старта берём у вида: переносу и демонтажу подбор локации не нужен.
      const s = await createSite(companyId, { ...form, kind, stage: kindDef?.startStage ?? 'lead' })
      await qc.invalidateQueries({ queryKey: ['pr-projects', companyId] })
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
      <div className="text-xs uppercase tracking-wide text-muted-foreground mb-0.5">{label}</div>
      <Input className="h-8 text-sm" value={form[k]} placeholder={ph}
        onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
    </div>
  )

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg w-[92vw]">
        <DialogHeader><DialogTitle className="text-base">Новый проект</DialogTitle></DialogHeader>
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Проект сразу получает номер. Право, мощность, экономика и документы
            добавляются в карточке по мере проработки — гейт не пустит дальше без них.
          </p>
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground mb-0.5">Вид работы</div>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
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
                {kindDef.label} — {kindDef.hint}. {kind === 'new_build'
                  ? 'Маршрут начнётся с подбора локации, договора и техприсоединения.'
                  : 'Подбор локации и договор пропускаем — маршрут начнётся с планирования работ.'}
              </p>
            )}
          </div>
          {field('title', 'Название проекта', 'ЭЗС на парковке ТЦ «Гринвич»')}
          <div className="grid grid-cols-2 gap-2">
            {field('region', 'Регион', 'Свердловская область')}
            {field('city', 'Город', 'Екатеринбург')}
          </div>
          {field('address', 'Адрес', 'ул. Кирова, 12')}
          {field('install_place', 'Место установки', 'ТЦ «Гринвич», парковка')}
          {field('owner', 'Собственник', 'если известен')}
          {!canSave && (
            <p className="text-xs text-muted-foreground">
              Нужен адрес или место установки — иначе проект не отличить от соседнего.
            </p>
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
