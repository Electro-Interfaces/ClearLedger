/**
 * Заведение проекта руками — площадка приходит не только файлом, но и звонком.
 *
 * Форма намеренно короткая: на входе известны адрес и от кого пришло, всё
 * остальное добывается по ходу и заполняется в карточке. Проект создаётся
 * стадией «Лид» и сразу получает номер.
 */
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { createSite } from '@/services/sitesService'

export function NewProjectDialog({ companyId, onClose, onCreated }: {
  companyId: string; onClose: () => void; onCreated: (id: string) => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    title: '', region: '', city: '', address: '', install_place: '', owner: '',
  })
  const [busy, setBusy] = useState(false)
  // Место должно быть опознаваемо: без адреса или названия объекта проект
  // невозможно ни найти, ни отличить от соседнего.
  const canSave = Boolean(form.address.trim() || form.install_place.trim())

  const save = async () => {
    setBusy(true)
    try {
      const s = await createSite(companyId, { ...form, stage: 'lead' })
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
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-0.5">{label}</div>
      <Input className="h-8 text-xs" value={form[k]} placeholder={ph}
        onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
    </div>
  )

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg w-[92vw]">
        <DialogHeader><DialogTitle className="text-base">Новый проект</DialogTitle></DialogHeader>
        <div className="space-y-2">
          <p className="text-[11px] text-muted-foreground">
            Заводится стадией «Лид» и получает номер. Право, мощность, экономика и документы
            добавляются в карточке по мере проработки — гейт не пустит дальше без них.
          </p>
          {field('title', 'Название проекта', 'ЭЗС на парковке ТЦ «Гринвич»')}
          <div className="grid grid-cols-2 gap-2">
            {field('region', 'Регион', 'Свердловская область')}
            {field('city', 'Город', 'Екатеринбург')}
          </div>
          {field('address', 'Адрес', 'ул. Кирова, 12')}
          {field('install_place', 'Место установки', 'ТЦ «Гринвич», парковка')}
          {field('owner', 'Собственник', 'если известен')}
          {!canSave && (
            <p className="text-[11px] text-muted-foreground">
              Нужен адрес или место установки — иначе проект не отличить от соседнего.
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onClose}>Отмена</Button>
            <Button size="sm" className="h-8 text-xs" disabled={!canSave || busy} onClick={save}>
              {busy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : null}Создать
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
