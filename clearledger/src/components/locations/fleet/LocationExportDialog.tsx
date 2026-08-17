/**
 * Модалка выгрузки точек: формат (Excel/CSV) + выбор колонок.
 * Экспортирует переданную выборку (filtered — текущие фильтры страницы).
 */
import { useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Download } from 'lucide-react'
import { toast } from 'sonner'
import type { ServiceLocation } from '@/types/location'
import type { LocationTypeDef } from '@/types/locationType'
import {
  LOCATION_COLUMNS, DEFAULT_EXPORT_COLUMNS,
  exportLocationsToExcel, exportLocationsToCsv,
} from './locationExportService'

export function LocationExportDialog({
  open, onOpenChange, locations, typeByCode,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  locations: ServiceLocation[]
  typeByCode: Map<string, LocationTypeDef>
}) {
  const [format, setFormat] = useState<'excel' | 'csv'>('excel')
  const [selected, setSelected] = useState<Set<string>>(() => new Set(DEFAULT_EXPORT_COLUMNS))

  const toggle = (key: string) => setSelected((s) => {
    const n = new Set(s)
    if (n.has(key)) n.delete(key); else n.add(key)
    return n
  })

  function handleExport() {
    if (selected.size === 0) { toast.error('Выберите хотя бы одну колонку'); return }
    if (locations.length === 0) { toast.error('Нет точек для выгрузки'); return }
    // Порядок колонок — как в LOCATION_COLUMNS (не в порядке клика).
    const keys = LOCATION_COLUMNS.filter((c) => selected.has(c.key)).map((c) => c.key)
    const ctx = { typeByCode }
    if (format === 'excel') exportLocationsToExcel(locations, keys, ctx)
    else exportLocationsToCsv(locations, keys, ctx)
    toast.success(`Выгружено точек: ${locations.length}`)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Экспорт точек ({locations.length})</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          <p className="text-xs text-muted-foreground">
            В файл попадёт текущая выборка с учётом фильтров страницы.
          </p>
          <div className="space-y-1.5">
            <Label>Формат</Label>
            <Select value={format} onValueChange={(v) => setFormat(v as 'excel' | 'csv')}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="excel">Excel (.xlsx)</SelectItem>
                <SelectItem value="csv">CSV (UTF-8, для Excel)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Колонки ({selected.size})</Label>
              <div className="flex gap-1">
                <Button variant="ghost" size="sm" className="h-7 text-xs"
                  onClick={() => setSelected(new Set(LOCATION_COLUMNS.map((c) => c.key)))}>Все</Button>
                <Button variant="ghost" size="sm" className="h-7 text-xs"
                  onClick={() => setSelected(new Set(DEFAULT_EXPORT_COLUMNS))}>По умолчанию</Button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-border/50 p-3">
              {LOCATION_COLUMNS.map((c) => (
                <label key={c.key} className="flex cursor-pointer items-center gap-2 text-sm">
                  <Checkbox checked={selected.has(c.key)} onCheckedChange={() => toggle(c.key)} />
                  <span className="truncate">{c.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button onClick={handleExport}><Download className="mr-2 h-4 w-4" /> Выгрузить</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
