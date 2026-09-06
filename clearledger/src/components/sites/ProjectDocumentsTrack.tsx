import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { listKinds } from '@/services/docsService'
import { getSiteTrack, type SiteDetail, type SiteDoc } from '@/services/sitesService'
import { promoteProjectFile } from '@/services/projectWorkspaceService'
import { TrackRow } from './ProjectTrackTab'

export function ProjectDocumentsTrack({ site, companyId }: { site: SiteDetail; companyId: string }) {
  const [offset, setOffset] = useState(0)
  const docs = useQuery({ queryKey: ['site-track', companyId, site.id, 'documents', offset],
    queryFn: () => getSiteTrack(companyId, site.id, { kind: 'doc', offset }) })
  return <section className="space-y-3 border-t pt-5">
    <h3 className="font-medium">Документы Трека · {docs.data?.total ?? '…'}</h3>
    <p className="text-sm text-muted-foreground">Файл, согласованная редакция и подписанный документ учитываются раздельно. Изменение содержимого требует нового согласования.</p>
    {docs.isPending && <p role="status" className="text-sm">Загрузка документов…</p>}
    {docs.isError && <div role="alert"><p className="text-sm">Документы не загрузились: {docs.error.message}</p><Button variant="outline" onClick={() => void docs.refetch()}>Повторить</Button></div>}
    {docs.data?.items.length === 0 && <p className="text-sm text-muted-foreground">Документы Трека пока не связаны с проектом. Оформите приложенный файл или свяжите существующий документ во вкладке «Трек».</p>}
    {docs.data?.items.map((doc) => <TrackRow key={doc.id} item={doc} site={site} companyId={companyId} />)}
    {(docs.data?.total ?? 0) > 40 && <div className="flex justify-between"><Button size="sm" variant="outline" disabled={!offset} onClick={() => setOffset(offset - 40)}>Назад</Button><Button size="sm" variant="outline" disabled={offset + 40 >= (docs.data?.total ?? 0)} onClick={() => setOffset(offset + 40)}>Далее</Button></div>}
  </section>
}

export function PromoteProjectFile({ file, companyId, siteId }: { file: SiteDoc; companyId: string; siteId: string }) {
  const [open, setOpen] = useState(false)
  const [kindId, setKindId] = useState('')
  const [title, setTitle] = useState(file.title || file.fileName || '')
  const navigate = useNavigate()
  const qc = useQueryClient()
  const kinds = useQuery({ queryKey: ['doc-kinds', companyId], queryFn: () => listKinds(companyId), enabled: open })
  const save = useMutation({ mutationFn: () => promoteProjectFile(companyId, siteId, file.id, kindId, title.trim()),
    onSuccess: (res) => { void qc.invalidateQueries({ queryKey: ['site-track'] }); setOpen(false); navigate(`/docs?view=all&doc=${res.doc_id}`) }, onError: (e) => toast.error(e.message) })
  return <><Button size="sm" variant="outline" disabled={!file.fileId} onClick={() => setOpen(true)}>Оформить документ</Button>
    <Dialog open={open} onOpenChange={(value) => { if (!save.isPending) setOpen(value) }}><DialogContent className="sm:max-w-md">
      <DialogHeader><DialogTitle>Оформить документ Трека</DialogTitle><DialogDescription>Файл {file.fileName} станет первой редакцией. Регистрация и согласование выполняются в Треке.</DialogDescription></DialogHeader>
      <label className="space-y-2 text-sm">Название<Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} /></label>
      <label className="space-y-2 text-sm">Вид документа<select aria-label="Вид документа" className="h-10 w-full rounded-md border bg-background px-3" value={kindId} onChange={(e) => setKindId(e.target.value)}>
        <option value="">Выберите вид документа</option>{kinds.data?.filter((k) => k.is_active).map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
      </select></label>{kinds.isError && <Button variant="outline" onClick={() => void kinds.refetch()}>Ошибка загрузки видов. Повторить</Button>}
      <Button disabled={!kindId || title.trim().length < 3 || save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Создание…' : 'Оформить и открыть'}</Button>
    </DialogContent></Dialog>
  </>
}
