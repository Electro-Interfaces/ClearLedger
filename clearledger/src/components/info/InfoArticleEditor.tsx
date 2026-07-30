/**
 * Редактор документа пространства — то, чем «Инфо» отличается от коробочной справки:
 * компания ведёт СВОИ документы (ЛНД, регламенты, приказы), а не только читает
 * инструкции поставщика.
 *
 * Платформенные статьи отсюда не правятся: их ведёт поставщик, и пространство не
 * должно менять общую нормативку у всех разом (то же правило на сервере —
 * `info_center.upsert_article`).
 *
 * Привязки — не «настройки для галочки»: указанный продукт и раздел определяют, где
 * документ всплывёт подсказкой в правой рельсе. Раздел выбирается из настоящего меню
 * продукта (`productModules`), а не вводится строкой: ключ, набранный руками, молча
 * никуда не привяжется.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useCompany } from '@/contexts/CompanyContext'
import { SPACE_PRODUCTS, productLabel } from '@/config/spaceProducts'
import { productModules } from '@/config/productAccess'
import {
  deleteInfoArticle, saveInfoArticle, type InfoArticleFull, type InfoKind, type InfoTree,
} from '@/services/infoService'
import { Markdown } from './Markdown'

/** Пласты, которые ведёт сама компания. Отраслевые нормы платформы сюда не входят. */
const KINDS: { key: InfoKind; label: string; hint: string }[] = [
  { key: 'lnd', label: 'Документ компании', hint: 'регламент, приказ, инструкция организации' },
  { key: 'guide', label: 'Инструкция', hint: 'как у нас принято работать' },
  { key: 'faq', label: 'Частый вопрос', hint: 'короткий ответ' },
  { key: 'norm', label: 'Норма', hint: 'требование, которому обязаны соответствовать' },
]

/** Приложения, к которым можно привязать документ: продукты разреза + приложения Ядра. */
const CORE_APPS = [
  { code: 'admin', label: 'Управление' },
  { code: 'connect', label: 'Подключения' },
  { code: 'support', label: 'Поддержка' },
  { code: 'chat', label: 'Чат' },
  { code: 'info', label: 'Инфо' },
]

type Binding = { app_code: string; section_key: string | null }

export function InfoArticleEditor({ companyId, article, categories, onClose, onSaved }: {
  companyId: string
  /** Пусто — заводим новый документ. */
  article?: InfoArticleFull | null
  categories: InfoTree['groups'][number]['categories']
  onClose: () => void
  onSaved: (id: string) => void
}) {
  const qc = useQueryClient()
  const { company } = useCompany()
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [kind, setKind] = useState<InfoKind>('lnd')
  const [categoryId, setCategoryId] = useState<string>('')
  const [docNumber, setDocNumber] = useState('')
  const [effectiveDate, setEffectiveDate] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [body, setBody] = useState('')
  const [bindings, setBindings] = useState<Binding[]>([])
  const [preview, setPreview] = useState(false)

  useEffect(() => {
    setTitle(article?.title ?? '')
    setSummary(article?.summary ?? '')
    setKind((article?.kind as InfoKind) ?? 'lnd')
    setCategoryId(article?.categoryId ?? '')
    setDocNumber(article?.docNumber ?? '')
    setEffectiveDate(article?.effectiveDate ?? '')
    setSourceUrl(article?.sourceUrl ?? '')
    setBody(article?.bodyMd ?? '')
    setBindings((article?.bindings ?? []).map((b) => ({ app_code: b.appCode, section_key: b.sectionKey })))
  }, [article])

  const apps = useMemo(() => [
    ...SPACE_PRODUCTS.map((p) => ({ code: p.code, label: productLabel(p, company.profileId) })),
    ...CORE_APPS,
  ], [company.profileId])

  const save = useMutation({
    mutationFn: () => saveInfoArticle(companyId, {
      id: article?.id,
      title: title.trim(),
      summary: summary.trim() || undefined,
      kind,
      category_id: categoryId || undefined,
      doc_number: docNumber.trim() || undefined,
      effective_date: effectiveDate || undefined,
      source_url: sourceUrl.trim() || undefined,
      body_md: body,
      bindings: bindings.filter((b) => b.app_code),
    }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['info-tree', companyId] })
      qc.invalidateQueries({ queryKey: ['info-ctx'] })
      qc.invalidateQueries({ queryKey: ['info-article', companyId] })
      toast.success(article ? 'Документ обновлён' : 'Документ заведён')
      onSaved(r.id)
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось сохранить'),
  })

  const remove = useMutation({
    mutationFn: () => deleteInfoArticle(companyId, article!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['info-tree', companyId] })
      toast.success('Документ удалён')
      onClose()
    },
    onError: (e) => toast.error((e as Error).message || 'Не удалось удалить'),
  })

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="flex max-h-[92vh] w-[96vw] max-w-4xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-4 py-3 text-left">
          <DialogTitle className="text-base">
            {article ? 'Документ пространства' : 'Новый документ пространства'}
          </DialogTitle>
          <DialogDescription className="text-xs">
            Виден только этому пространству. Привязка к продукту и разделу выводит документ
            подсказкой на нужный экран.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
          <div className="grid gap-3 md:grid-cols-[1fr_220px]">
            <div className="space-y-1">
              <Label className="text-xs">Название</Label>
              <Input value={title} onChange={(e) => setTitle(e.target.value)}
                placeholder="Регламент приёмки нефтепродуктов" className="h-9" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Пласт</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as InfoKind)}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {KINDS.map((k) => (
                    <SelectItem key={k.key} value={k.key}>
                      <span className="text-sm">{k.label}</span>
                      <span className="ml-2 text-[11px] text-muted-foreground">{k.hint}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">О чём документ, одной строкой</Label>
            <Input value={summary} onChange={(e) => setSummary(e.target.value)}
              placeholder="Порядок приёма бензовоза и сверки с ТТН" className="h-9" />
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <div className="space-y-1">
              <Label className="text-xs">Раздел</Label>
              <Select value={categoryId || 'none'} onValueChange={(v) => setCategoryId(v === 'none' ? '' : v)}>
                <SelectTrigger className="h-9"><SelectValue placeholder="без раздела" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">без раздела</SelectItem>
                  {categories.map((c) => <SelectItem key={c.id} value={c.id}>{c.title}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Номер</Label>
              <Input value={docNumber} onChange={(e) => setDocNumber(e.target.value)}
                placeholder="Приказ № 14" className="h-9" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Действует с</Label>
              <Input type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} className="h-9" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Ссылка на источник</Label>
              <Input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)}
                placeholder="https://…" className="h-9" />
            </div>
          </div>

          {/* Привязки — настройка «где показывать». Раздел выбирается из настоящего
              меню продукта: ключ, набранный руками, никуда не привяжется. */}
          <div className="space-y-1.5 rounded-lg border border-border/60 p-2.5">
            <div className="flex items-center justify-between">
              <Label className="text-xs">Где показывать подсказкой</Label>
              <Button size="sm" variant="ghost" className="h-7 text-xs"
                onClick={() => setBindings((b) => [...b, { app_code: '', section_key: null }])}>
                <Plus className="mr-1 h-3.5 w-3.5" /> Добавить место
              </Button>
            </div>
            {bindings.length === 0 && (
              <p className="text-[11px] text-muted-foreground">
                Без привязок документ живёт только в общем дереве «Инфо».
              </p>
            )}
            {bindings.map((b, i) => {
              const sections = productModules(b.app_code, company.profileId)
              return (
                <div key={i} className="flex items-center gap-2">
                  <Select value={b.app_code || 'none'}
                    onValueChange={(v) => setBindings((arr) => arr.map((x, j) =>
                      j === i ? { app_code: v === 'none' ? '' : v, section_key: null } : x))}>
                    <SelectTrigger className="h-8 w-[190px] text-xs"><SelectValue placeholder="приложение" /></SelectTrigger>
                    <SelectContent>
                      {apps.map((a) => <SelectItem key={a.code} value={a.code}>{a.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Select value={b.section_key || 'all'} disabled={!b.app_code || sections.length === 0}
                    onValueChange={(v) => setBindings((arr) => arr.map((x, j) =>
                      j === i ? { ...x, section_key: v === 'all' ? null : v } : x))}>
                    <SelectTrigger className="h-8 flex-1 text-xs">
                      <SelectValue placeholder={sections.length ? 'весь продукт' : 'весь продукт'} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">весь продукт</SelectItem>
                      {sections.map((m) => (
                        <SelectItem key={m.code} value={m.code}>{m.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <button type="button" title="Убрать"
                    onClick={() => setBindings((arr) => arr.filter((_, j) => j !== i))}
                    className="text-muted-foreground hover:text-destructive">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )
            })}
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <Label className="text-xs">Текст (Markdown)</Label>
              <button type="button" onClick={() => setPreview((v) => !v)}
                className="text-[11px] text-muted-foreground hover:text-foreground">
                {preview ? 'править' : 'предпросмотр'}
              </button>
            </div>
            {preview ? (
              <div className="min-h-[240px] rounded-md border border-border/60 px-3 py-2">
                <Markdown content={body} />
              </div>
            ) : (
              <Textarea value={body} onChange={(e) => setBody(e.target.value)} rows={14}
                className="font-mono text-xs"
                placeholder={'## Порядок\n\n1. Проверить пломбы\n2. Снять замер до слива\n'} />
            )}
          </div>
        </div>

        <DialogFooter className="flex-row items-center gap-2 border-t px-4 py-2.5">
          {article && (
            <Button variant="ghost" size="sm" className="mr-auto text-destructive hover:text-destructive"
              onClick={() => remove.mutate()} disabled={remove.isPending}>
              <Trash2 className="mr-1 h-3.5 w-3.5" /> Удалить
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onClose}>Отмена</Button>
          <Button size="sm" disabled={!title.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
