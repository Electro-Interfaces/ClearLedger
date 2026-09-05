import { useDeferredValue, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { openDB } from 'idb'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCompany } from '@/contexts/CompanyContext'
import { useAuth } from '@/contexts/AuthContext'
import { useTrackDraft } from '@/hooks/useTrackDraft'
import { searchCounterpartiesPaged } from '@/services/referenceService'
import { listTaskPeople } from '@/services/tasksService'
import { readDocumentText, suggestDocumentFields } from '@/services/docFileText'
import * as docsService from '@/services/docsService'
import type { DocKind } from '@/services/docsService'

interface Props {
  companyId: string; kinds: DocKind[]; defaultFamily?: string; initialTitle?: string
  summary?: string; subjectRef?: string; onClose: () => void; onCreated: (id: string) => void
}

function fileStore() {
  return openDB('track-draft-files', 1, { upgrade(db) { db.createObjectStore('files') } })
}

export function NewDocDialog(props: Props) {
  const { user } = useAuth()
  const draftKey = `track:new-doc:${user?.id}:${props.companyId}:${props.defaultFamily || ''}:${props.subjectRef || ''}`
  return <NewDocForm key={draftKey} {...props} draftKey={draftKey} />
}

function NewDocForm({ companyId, kinds, defaultFamily, initialTitle, summary, subjectRef, onClose, onCreated, draftKey }: Props & { draftKey: string }) {
  const { organizations, organizationId } = useCompany()
  const suited = defaultFamily ? kinds.filter((kind) => kind.family === defaultFamily) : kinds
  const draft = useTrackDraft(draftKey, {
    kindId: suited[0]?.id ?? kinds[0]?.id ?? '', title: initialTitle ?? '', counterparty: '', counterpartyId: '',
    externalNumber: '', externalDate: '', organizationId: organizationId ?? (organizations.length === 1 ? organizations[0].id : ''),
    responsibleId: '', dueAt: '', createdId: '', fileKey: '', fileName: '', fileHash: '',
  })
  const form = draft.value
  const change = (values: Partial<typeof form>) => draft.save((previous) => ({ ...previous, ...values }))
  const [file, setFile] = useState<File | null>(null)
  const [fileBusy, setFileBusy] = useState(!!form.fileKey)
  const [fileError, setFileError] = useState('')
  const [suggestions, setSuggestions] = useState<ReturnType<typeof suggestDocumentFields> | null>(null)
  const [extractError, setExtractError] = useState('')
  const [duplicateAccepted, setDuplicateAccepted] = useState(false)
  const [restoreFile] = useState({ key: form.fileKey, name: form.fileName })
  const selection = useRef(0)
  const kind = kinds.find((item) => item.id === form.kindId)
  const incoming = kind?.direction === 'in'
  const partySearch = useDeferredValue(form.counterparty)
  const parties = useQuery({ queryKey: ['track-counterparties', companyId, partySearch],
    queryFn: () => searchCounterpartiesPaged(companyId, { q: partySearch, limit: 20 }), staleTime: 60_000 })
  const people = useQuery({ queryKey: ['task-people', companyId], queryFn: () => listTaskPeople(companyId), staleTime: 300_000 })
  const currentIdentity = JSON.stringify({ file_sha256: form.fileHash,
    external_number: form.externalNumber, external_date: form.externalDate,
    counterparty_id: form.counterpartyId, counterparty_name: form.counterparty })
  const identity = useDeferredValue(currentIdentity)
  const hasIdentity = !!form.fileHash || !!(form.externalNumber && form.counterparty)
  const duplicates = useQuery({ queryKey: ['doc-duplicates', companyId, identity],
    queryFn: () => docsService.duplicateCandidates(companyId,
      Object.fromEntries(Object.entries(JSON.parse(identity) as Record<string, string>).filter(([, value]) => !!value))),
    enabled: hasIdentity && !form.createdId, retry: false })
  useEffect(() => { setDuplicateAccepted(false) }, [identity])
  useEffect(() => {
    let active = true
    const restore = async () => {
      if (!restoreFile.key) return
      try {
        const db = await fileStore()
        const saved = await db.get('files', restoreFile.key)
        if (active) {
          if (saved instanceof File) setFile(saved)
          else setFileError(`Выберите файл «${restoreFile.name}» повторно`)
        }
      } catch { if (active) setFileError('Не удалось восстановить файл. Выберите его повторно.') }
      finally { if (active) setFileBusy(false) }
    }
    void restore()
    return () => { active = false }
  }, [restoreFile])

  const selectFile = async (selected: File | null) => {
    if (!selected) return
    if (selected.size > 25 * 1024 * 1024) { setFileError('Максимальный размер файла — 25 МБ'); return }
    if (!/\.(pdf|docx?|xlsx?|txt|png|jpe?g|webp)$/i.test(selected.name)) {
      setFileError('Поддерживаются PDF, Word, Excel, TXT и изображения PNG, JPEG, WebP'); return
    }
    const generation = ++selection.current
    setFileBusy(true); setFileError(''); setExtractError(''); setSuggestions(null); setFile(selected)
    try {
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await selected.arrayBuffer()))]
        .map((byte) => byte.toString(16).padStart(2, '0')).join('')
      const fileKey = form.fileKey || `${draftKey}:${crypto.randomUUID()}`
      try { const db = await fileStore(); await db.put('files', selected, fileKey) }
      catch { setFileError('Файл готов к отправке, но браузер не сохранил копию. После закрытия выберите его повторно.') }
      if (generation === selection.current) change({ fileKey, fileName: selected.name, fileHash: hash })
    } catch { setFileError('Не удалось подготовить файл. Выберите его повторно.'); setFile(null) }
    finally { if (generation === selection.current) setFileBusy(false) }
  }
  const extract = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Выберите файл')
      const result = await readDocumentText(file, true)
      if (!result.text.trim()) throw new Error('Текст не найден. Заполните реквизиты вручную.')
      return suggestDocumentFields(file.name, result.text)
    },
    onSuccess: (values) => { setSuggestions(values); setExtractError('') },
    onError: (error) => setExtractError(error.message),
  })
  const cleanupFile = async () => {
    if (form.fileKey) { try { const db = await fileStore(); await db.delete('files', form.fileKey) } catch { /* Очистка недоступного хранилища не блокирует завершение. */ } }
  }
  const create = useMutation({
    mutationFn: async () => {
      let id = form.createdId
      if (!id) {
        const document = await docsService.createDoc(companyId, {
          kind_id: form.kindId, title: form.title.trim(), summary: summary || undefined, subject_ref: subjectRef || undefined,
          organization_id: form.organizationId || null, counterparty_id: form.counterpartyId || null,
          counterparty_name: form.counterparty.trim(), external_number: form.externalNumber.trim() || null,
          external_date: form.externalDate || null, responsible_id: form.responsibleId || null,
          due_at: form.dueAt ? new Date(form.dueAt).toISOString() : null,
        })
        id = document.id
        change({ createdId: id })
      }
      if (file) await docsService.uploadVersion(companyId, id, file)
      return id
    },
    onSuccess: async (id) => { await cleanupFile(); draft.clear(); onCreated(id) },
  })
  const matches = duplicates.data?.docs ?? []
  const missing = !kind ? 'Выберите вид документа'
    : organizations.length > 0 && !form.organizationId ? 'Выберите наше юрлицо'
      : !form.title.trim() ? 'Впишите заголовок'
        : form.fileName && !file ? `Выберите файл «${form.fileName}» повторно` : null
  const blocked = !!missing || fileBusy || extract.isPending || create.isPending || identity !== currentIdentity
    || (!form.createdId && hasIdentity && (duplicates.isFetching || duplicates.isPending || (matches.length > 0 || duplicates.isError) && !duplicateAccepted))

  return <Dialog open onOpenChange={(value) => { if (!value && !create.isPending && !fileBusy) onClose() }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
      <DialogHeader><DialogTitle>Новый документ</DialogTitle>
        <DialogDescription>Начните с файла или заполните реквизиты. Регистрационный номер выдаётся отдельно.</DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        {form.createdId && <div role="status" className="space-y-2 rounded-md border p-3 text-sm">
          <p>Карточка создана. Осталось приложить файл.</p>
          <Button variant="outline" size="sm" onClick={() => onCreated(form.createdId)}>Открыть созданную карточку</Button>
        </div>}
        <fieldset disabled={create.isPending || fileBusy || extract.isPending} className="space-y-2 rounded-md border p-3">
          <Label htmlFor="new-doc-file">Основной файл</Label>
          <Input id="new-doc-file" type="file" accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.jpg,.jpeg,.png,.webp"
            onChange={(event) => { void selectFile(event.target.files?.[0] ?? null); event.target.value = '' }} />
          {form.fileName && <p className="break-words text-sm">{form.fileName}</p>}
          {fileBusy && <p role="status" className="text-sm">Подготавливаем файл…</p>}
          {fileError && <p role="alert" className="text-sm text-destructive">{fileError}</p>}
          {file && !form.createdId && <Button size="sm" variant="outline" onClick={() => extract.mutate()}>
            {extract.isPending ? 'Читаем файл…' : 'Предложить реквизиты из файла'}
          </Button>}
          {form.fileName && !form.createdId && <Button size="sm" variant="ghost" onClick={async () => {
            await cleanupFile(); setFile(null); setFileError(''); setSuggestions(null); setExtractError('')
            change({ fileKey: '', fileName: '', fileHash: '' })
          }}>Убрать файл</Button>}
        </fieldset>
        {extractError && <p role="alert" className="text-sm text-destructive">{extractError}</p>}
        {suggestions && <section className="space-y-2 rounded-md border p-3 text-sm">
          <p className="font-medium">Проверьте распознанное</p><p>Заголовок: {suggestions.title}</p>
          <p>Номер: {suggestions.externalNumber || 'не найден'} · Дата: {suggestions.externalDate || 'не найдена'}</p>
          <Button size="sm" variant="outline" onClick={() => {
            change({ title: suggestions.title, ...(incoming && suggestions.externalNumber ? { externalNumber: suggestions.externalNumber } : {}),
              ...(incoming && suggestions.externalDate ? { externalDate: suggestions.externalDate } : {}) }); setSuggestions(null)
          }}>Применить реквизиты</Button>
        </section>}
        <fieldset disabled={create.isPending || !!form.createdId} className="space-y-3">
          <div className="space-y-1.5"><Label htmlFor="new-doc-kind">Вид документа</Label>
            <select id="new-doc-kind" value={form.kindId} onChange={(event) => change({ kindId: event.target.value })}
              className="h-11 w-full rounded-md border bg-background px-2 text-sm">
              {(suited.length ? suited : kinds).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></div>
          {organizations.length > 0 && <div className="space-y-1.5"><Label htmlFor="new-doc-organization">Наше юрлицо</Label>
            <select id="new-doc-organization" value={form.organizationId} onChange={(event) => change({ organizationId: event.target.value })}
              className="h-11 w-full rounded-md border bg-background px-2 text-sm">
              <option value="">Выберите юрлицо</option>
              {organizations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></div>}
          <div className="space-y-1.5"><Label htmlFor="new-doc-title">Заголовок</Label>
            <Input id="new-doc-title" value={form.title} maxLength={500} onChange={(event) => change({ title: event.target.value })} placeholder="О чём документ" /></div>
          <div className="space-y-1.5"><Label htmlFor="new-doc-counterparty">{incoming ? 'От кого' : 'Кому'}</Label>
            <Input id="new-doc-counterparty" value={form.counterparty} maxLength={500} placeholder="Название или ИНН для поиска"
              onChange={(event) => change({ counterparty: event.target.value, counterpartyId: '' })} />
            {!form.counterpartyId && !!parties.data?.items.length && <div className="max-h-32 overflow-y-auto rounded-md border">
              {parties.data.items.map((party) => <button key={party.id} type="button"
                className="block min-h-11 w-full px-3 py-2 text-left text-sm hover:bg-accent focus-visible:bg-accent"
                onClick={() => change({ counterparty: party.name, counterpartyId: party.id })}>
                {party.name}{party.inn ? ` · ИНН ${party.inn}` : ''}
              </button>)}
            </div>}
            <p className="text-xs text-muted-foreground">{form.counterpartyId ? 'Выбран контрагент из справочника' : 'Выберите из справочника или оставьте введённое название.'}</p>
            {parties.isError && <p className="text-xs text-destructive">Справочник не загрузился. Название можно ввести вручную.</p>}
          </div>
          {incoming && <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="new-doc-external-number">Их исходящий номер</Label>
              <Input id="new-doc-external-number" value={form.externalNumber} maxLength={200} onChange={(event) => change({ externalNumber: event.target.value })} /></div>
            <div className="space-y-1.5"><Label htmlFor="new-doc-external-date">Дата их документа</Label>
              <Input id="new-doc-external-date" type="date" value={form.externalDate} onChange={(event) => change({ externalDate: event.target.value })} /></div>
          </div>}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5"><Label htmlFor="new-doc-responsible">Ответственный</Label>
              <select id="new-doc-responsible" value={form.responsibleId} disabled={people.isPending || people.isError}
                onChange={(event) => change({ responsibleId: event.target.value })} className="h-11 w-full rounded-md border bg-background px-2 text-sm">
                <option value="">Не назначен</option>
                {people.data?.people.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
              </select></div>
            <div className="space-y-1.5"><Label htmlFor="new-doc-due">Срок исполнения</Label>
              <Input id="new-doc-due" type="datetime-local" value={form.dueAt} onChange={(event) => change({ dueAt: event.target.value })} /></div>
          </div>
          {people.isError && <Button variant="outline" size="sm" onClick={() => void people.refetch()}>Повторить загрузку сотрудников</Button>}
        </fieldset>
        {!form.createdId && hasIdentity && <section className="space-y-2 text-sm">
          {duplicates.isFetching && <p role="status">Проверяем возможные дубли…</p>}
          {matches.length > 0 && <><p className="font-medium">Найдены похожие документы</p>
            {matches.map((document) => <button key={document.id} type="button" className="block text-left text-primary underline"
              onClick={() => onCreated(document.id)}>{document.reg_number || document.external_number || 'Черновик'} · {document.title}</button>)}</>}
          {duplicates.isError && <div role="alert">Не удалось проверить дубли. <Button size="sm" variant="outline" onClick={() => void duplicates.refetch()}>Повторить проверку</Button></div>}
          {(matches.length > 0 || duplicates.isError) && <label className="flex min-h-11 items-center gap-2">
            <input type="checkbox" checked={duplicateAccepted} onChange={(event) => setDuplicateAccepted(event.target.checked)} />
            {matches.length ? 'Создать отдельный документ' : 'Продолжить без проверки дублей'}
          </label>}
        </section>}
        {create.isError && <div role="alert" className="space-y-2 text-sm text-destructive">
          <p>{form.createdId ? 'Карточка уже создана. Повторная попытка добавит файл в эту карточку.' : 'Не удалось завершить создание. Проверьте список документов перед повторной попыткой.'} {create.error.message}</p>
        </div>}
        <p role="status" className="text-xs text-muted-foreground">{draft.error ? 'Черновик хранится только в памяти. Не перезагружайте страницу.' : 'Черновик восстанавливается в этой вкладке. Закрытие формы его не удаляет.'}</p>
      </div>
      <DialogFooter className="gap-2 sm:justify-between">
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" disabled={create.isPending || fileBusy} onClick={async () => { await cleanupFile(); draft.clear(); onClose() }}>
            {form.createdId ? 'Завершить без файла' : 'Удалить черновик'}
          </Button>
          <Button variant="outline" disabled={create.isPending || fileBusy} onClick={onClose}>Закрыть</Button>
        </div>
        <Button disabled={blocked} title={missing ?? undefined} onClick={() => create.mutate()}>
          {create.isPending ? 'Сохраняем…' : form.createdId ? 'Повторить загрузку файла' : 'Завести документ'}
        </Button>
      </DialogFooter>
      {missing && <p className="text-xs text-muted-foreground">{missing}</p>}
    </DialogContent>
  </Dialog>
}

export default NewDocDialog
