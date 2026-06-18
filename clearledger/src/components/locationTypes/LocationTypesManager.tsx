/**
 * Каталог типов точек — список встроенных + кастомных типов компании с
 * созданием/правкой/удалением. Встроенные не удаляются (правит суперадмин).
 */
import { useState, type ReactNode } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'
import { useLocationTypes } from '@/hooks/useLocationTypes'
import { deleteLocationType } from '@/services/locationTypeService'
import { resolveLocationIcon } from './locationIcons'
import { LocationTypeEditDialog } from './LocationTypeEditDialog'
import type { LocationTypeDef } from '@/types/locationType'

export function LocationTypesManager({
  children,
  onChanged,
}: {
  children: ReactNode
  onChanged?: () => void
}) {
  const [open, setOpen] = useState(false)
  const types = useLocationTypes()
  const qc = useQueryClient()

  async function handleDelete(t: LocationTypeDef) {
    try {
      await deleteLocationType(t.id)
      await qc.invalidateQueries({ queryKey: ['location-types'] })
      toast.success(`Тип «${t.name}» удалён`)
      onChanged?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось удалить тип')
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Типы точек обслуживания</DialogTitle>
        </DialogHeader>

        <div className="flex justify-end">
          <LocationTypeEditDialog onSaved={onChanged}>
            <Button size="sm">
              <Plus className="h-4 w-4 mr-1.5" /> Создать тип
            </Button>
          </LocationTypeEditDialog>
        </div>

        <div className="space-y-2">
          {types.map((t) => {
            const Icon = resolveLocationIcon(t.icon)
            return (
              <div key={t.id} className="flex items-center gap-3 rounded-md border border-border/50 p-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-md bg-muted shrink-0">
                  <Icon className="h-4.5 w-4.5 text-muted-foreground" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium">{t.name}</span>
                    <code className="text-[11px] text-muted-foreground">{t.code}</code>
                    {t.isBuiltin
                      ? <Badge variant="secondary" className="text-[10px]">встроенный</Badge>
                      : <Badge variant="outline" className="text-[10px]">кастомный</Badge>}
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    единица: {t.unit || '—'} · полей: {t.fields.length}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <LocationTypeEditDialog type={t} onSaved={onChanged}>
                    <Button variant="ghost" size="icon" className="h-7 w-7">
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                  </LocationTypeEditDialog>
                  {!t.isBuiltin && (
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive">
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Удалить тип «{t.name}»?</AlertDialogTitle>
                          <AlertDialogDescription>
                            Точки с этим типом останутся, но тип пропадёт из списка выбора.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Отмена</AlertDialogCancel>
                          <AlertDialogAction onClick={() => handleDelete(t)}>Удалить</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </DialogContent>
    </Dialog>
  )
}
