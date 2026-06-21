/**
 * Страница «Файлы и документы» — ручная загрузка документов,
 * которые не покрываются автоматическими каналами (STS, MSTO, TradeCorp).
 *
 * Идеология: это просто ещё один «канал», только запускается человеком.
 * Менеджер выбирает тип документа, точку и дату — система помечает
 * запись теми же атрибутами что и автозагруженные документы.
 */

import { useState, useCallback, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Upload, FileText, Image, FileSpreadsheet, File, Trash2, MapPin, Filter,
} from 'lucide-react'
import { toast } from 'sonner'
import { nanoid } from 'nanoid'
import { format } from 'date-fns'
import { useLocations } from '@/hooks/useLocations'
import { useFilters } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'

type DocKind = 'shift_report' | 'receipt' | 'invoice' | 'bank_statement' | 'cash_doc' | 'contract' | 'other'

interface IntakeFile {
  id: string
  name: string
  size: number
  mime: string
  status: 'loaded' | 'processing' | 'classified' | 'error'
  loadedAt: string
  docKind: DocKind
  docKindId: string   // id выбранного варианта (для подписи; несколько вариантов могут делить kind)
  locationId?: string
  docDate?: string
  comment?: string
}

// Запись типа документа в выпадающем списке. id — уникальный ключ варианта
// (стабилен для key/Select), kind — на каком виде сохраняется (атрибут записи).
interface DocKindOption { id: string; kind: DocKind; label: string; hint: string }

// Набор типов документов для топливного/розничного (1С) профиля.
const DOC_KINDS_FUEL: DocKindOption[] = [
  { id: 'shift_report', kind: 'shift_report', label: 'Сменный отчёт', hint: 'ОРП, фискальный документ за смену' },
  { id: 'receipt', kind: 'receipt', label: 'ТТН / Поступление', hint: 'Накладная на приём топлива или товара' },
  { id: 'invoice', kind: 'invoice', label: 'Счёт-фактура', hint: 'СФ от поставщика для НДС' },
  { id: 'bank_statement', kind: 'bank_statement', label: 'Банковская выписка', hint: 'Платёжный документ из банка' },
  { id: 'cash_doc', kind: 'cash_doc', label: 'Кассовый документ', hint: 'ПКО / РКО / акт инкассации' },
  { id: 'contract', kind: 'contract', label: 'Договор / соглашение', hint: 'Контракт с контрагентом' },
  { id: 'other', kind: 'other', label: 'Прочее', hint: 'Не подходит под другие типы' },
]

// Набор типов документов для энергетического профиля (ЭЗС, инфраструктура).
const DOC_KINDS_ENERGY: DocKindOption[] = [
  { id: 'maintenance_act', kind: 'receipt', label: 'Акт ТО оборудования', hint: 'Плановое / аварийное обслуживание' },
  { id: 'defect_sheet', kind: 'other', label: 'Дефектная ведомость', hint: 'Перечень выявленных дефектов' },
  { id: 'inspection_journal', kind: 'shift_report', label: 'Журнал обходов', hint: 'Записи о плановых обходах объекта' },
  { id: 'work_permit', kind: 'contract', label: 'Наряд-допуск', hint: 'Разрешение на проведение работ' },
  { id: 'supplier_invoice', kind: 'invoice', label: 'Счёт поставщика', hint: 'Счёт / счёт-фактура от контрагента' },
  { id: 'payment_order', kind: 'bank_statement', label: 'Платёжное поручение', hint: 'Платёжный документ' },
  { id: 'other', kind: 'other', label: 'Прочее', hint: 'Не подходит под другие типы' },
]

const FILE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  'application/pdf': FileText,
  'image/': Image,
  'application/vnd.openxmlformats': FileSpreadsheet,
  'application/vnd.ms-excel': FileSpreadsheet,
  'text/csv': FileSpreadsheet,
}

function getFileIcon(mimeType: string) {
  for (const [key, Icon] of Object.entries(FILE_ICONS)) {
    if (mimeType.startsWith(key)) return Icon
  }
  return File
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

export function IntakePage() {
  const [files, setFiles] = useState<IntakeFile[]>([])
  const [dragging, setDragging] = useState(false)

  // Параметры для следующей загрузки — применяются ко всем файлам,
  // которые будут загружены drop-zone'ом следующий раз.
  const locations = useLocations()   // точки активной компании, рефетч при переключении
  const { locationIds: globalLocIds } = useFilters()

  // Набор типов документов зависит от профиля компании: для энергетики
  // (ЭЗС РусГидро) — энерго-документы, иначе — топливные/1С.
  const { company } = useCompany()
  const isEnergy = company.profileId === 'energy'
  const docKinds = isEnergy ? DOC_KINDS_ENERGY : DOC_KINDS_FUEL

  // Если в шапке выбрана ровно одна точка — предзаполняем её
  const defaultLocationId =
    globalLocIds.length === 1 ? globalLocIds[0] : ''

  // pendingKindId — id выбранного варианта (последний = «Прочее») из активного набора.
  const [pendingKindId, setPendingKindId] = useState<string>(() => docKinds[docKinds.length - 1].id)
  const [pendingLocationId, setPendingLocationId] = useState<string>(defaultLocationId)
  const [pendingDate, setPendingDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'))

  // Если набор сменился (профиль) и выбранного id в нём нет — откатываемся к «Прочее».
  const pendingOption = docKinds.find((k) => k.id === pendingKindId) ?? docKinds[docKinds.length - 1]

  const handleFiles = useCallback((fileList: FileList) => {
    const newFiles: IntakeFile[] = Array.from(fileList).map((f) => ({
      id: nanoid(8),
      name: f.name,
      size: f.size,
      mime: f.type,
      status: 'loaded' as const,
      loadedAt: new Date().toISOString(),
      docKind: pendingOption.kind,
      docKindId: pendingOption.id,
      locationId: pendingLocationId || undefined,
      docDate: pendingDate,
    }))
    setFiles((prev) => [...newFiles, ...prev])
    toast.success(`Загружено ${newFiles.length} файл(ов)`)
  }, [pendingOption, pendingLocationId, pendingDate])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files)
    }
  }, [handleFiles])

  const handleRemove = (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id))
  }

  const locationName = useMemo(() => {
    const map = new Map(locations.map((l) => [l.id, l]))
    return (id?: string) => id ? (map.get(id)?.name ?? '—') : '—'
  }, [locations])

  // Подпись по id варианта — ищем в обоих наборах (файл мог быть загружен
  // под любым профилем); фолбэк — по виду документа.
  const kindLabel = useMemo(() => {
    const map = new Map(
      [...DOC_KINDS_FUEL, ...DOC_KINDS_ENERGY].map((k) => [k.id, k.label]),
    )
    return (id: string, kind: DocKind) => map.get(id) ?? kind
  }, [])

  return (
    <div className="space-y-4 max-w-5xl">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Файлы и документы</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Ручная загрузка документов, которые не приходят через автоматические каналы
          (банковские выписки, отдельные ТТН, договоры, прочее).
        </p>
      </div>

      {/* Параметры следующей загрузки */}
      <Card className="py-3 gap-2">
        <CardHeader className="pb-0">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Filter className="h-3.5 w-3.5 text-muted-foreground" />
            Параметры загрузки
          </CardTitle>
          <CardDescription className="text-[11px]">
            Применятся к следующим перетащенным файлам — менеджер сам указывает контекст.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0 pb-0">
          <div className="grid sm:grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs">Тип документа</Label>
              <Select value={pendingOption.id} onValueChange={setPendingKindId}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {docKinds.map((k) => (
                    <SelectItem key={k.id} value={k.id} className="text-xs">
                      <div className="flex flex-col">
                        <span>{k.label}</span>
                        <span className="text-[10px] text-muted-foreground">{k.hint}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Точка обслуживания</Label>
              <Select value={pendingLocationId || 'none'}
                onValueChange={(v) => setPendingLocationId(v === 'none' ? '' : v)}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Без привязки" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none" className="text-xs text-muted-foreground">
                    Без привязки
                  </SelectItem>
                  {locations.map((l) => (
                    <SelectItem key={l.id} value={l.id} className="text-xs">
                      <span className="font-mono text-muted-foreground mr-2">{l.code}</span>
                      {l.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Дата документа</Label>
              <Input type="date" value={pendingDate}
                onChange={(e) => setPendingDate(e.target.value)}
                className="h-8 text-xs" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Drop zone */}
      <Card
        className={`py-3 gap-2 border-2 border-dashed transition-colors cursor-pointer ${
          dragging ? 'border-primary bg-primary/5' : 'border-border/60 hover:border-primary/50'
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => {
          const input = document.createElement('input')
          input.type = 'file'
          input.multiple = true
          input.accept = '.pdf,.xlsx,.xls,.csv,.xml,.jpg,.jpeg,.png,.tiff,.eml,.txt,.json,.doc,.docx'
          input.onchange = () => { if (input.files) handleFiles(input.files) }
          input.click()
        }}
      >
        <CardContent className="flex flex-col items-center justify-center py-8 gap-2">
          <Upload className={`h-8 w-8 ${dragging ? 'text-primary' : 'text-muted-foreground/40'}`} />
          <div className="text-center">
            <p className="text-sm font-medium">
              {dragging ? 'Отпустите файлы' : 'Перетащите файлы сюда'}
            </p>
            <p className="text-[10px] text-muted-foreground mt-1">
              или нажмите для выбора · PDF · Excel · CSV · XML · фото · Email · до 50 МБ
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Список загруженных */}
      {files.length > 0 && (
        <Card className="py-3 gap-2">
          <CardHeader className="pb-0">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                Загруженные
                <span className="text-xs text-muted-foreground font-normal ml-2 tabular-nums">
                  {files.length}
                </span>
              </CardTitle>
              <Button variant="ghost" size="sm" className="text-xs h-7 text-muted-foreground"
                onClick={() => { setFiles([]); toast.info('Список очищен') }}>
                Очистить
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-0 pb-0">
            <div className="grid grid-cols-[1fr_140px_160px_100px_70px_40px] gap-3 px-2 py-1.5 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide border-b border-border/40">
              <span>Файл</span>
              <span>Тип</span>
              <span>Точка</span>
              <span>Дата</span>
              <span className="text-right">Размер</span>
              <span></span>
            </div>
            <div className="max-h-[420px] overflow-y-auto -mx-2 px-2">
              {files.map((f) => {
                const IconComp = getFileIcon(f.mime)
                return (
                  <div key={f.id}
                    className="grid grid-cols-[1fr_140px_160px_100px_70px_40px] gap-3 items-center px-2 py-2 text-xs border-b border-border/30 hover:bg-accent/30 last:border-b-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <IconComp className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <span className="font-medium truncate">{f.name}</span>
                    </div>
                    <Badge variant="outline" className="text-[10px] h-5 px-1.5 justify-self-start">
                      {kindLabel(f.docKindId, f.docKind)}
                    </Badge>
                    <div className="min-w-0 flex items-center gap-1">
                      {f.locationId ? (
                        <>
                          <MapPin className="h-3 w-3 text-muted-foreground shrink-0" />
                          <span className="truncate">{locationName(f.locationId)}</span>
                        </>
                      ) : (
                        <span className="text-muted-foreground/60">—</span>
                      )}
                    </div>
                    <span className="text-muted-foreground tabular-nums text-[11px]">
                      {f.docDate ? format(new Date(f.docDate), 'dd.MM.yyyy') : '—'}
                    </span>
                    <span className="text-right text-muted-foreground tabular-nums">
                      {formatSize(f.size)}
                    </span>
                    <Button variant="ghost" size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive justify-self-center"
                      onClick={() => handleRemove(f.id)}>
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Подсказка */}
      <Card className="py-3 gap-2 border-l-2 border-l-primary/40">
        <CardContent className="pt-0 pb-0">
          <p className="text-xs text-muted-foreground">
            <Badge variant="outline" className="text-[9px] h-4 px-1 mr-1">i</Badge>
            После загрузки и распознавания документы попадут в нормализованную БД
            вместе с автоматически загруженными — с теми же атрибутами (тип, станция, период)
            и будут видны на «Загружено» соответствующего канала «Ручной приём».
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

export default IntakePage
