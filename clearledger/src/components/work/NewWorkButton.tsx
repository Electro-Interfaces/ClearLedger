/**
 * Одна кнопка «Создать» на весь «Трек».
 *
 * До этого точка входа зависела от экрана: поручение ставили только в реестре
 * поручений, документ заводили только в реестре документов, а на общей ленте, на
 * доске, в очереди «На мне» и в планировании не было ничего. Человек, который
 * пришёл заводить работу, сначала искал, откуда её заводят.
 *
 * Разделение остаётся, но не в навигации, а в выборе: «что вы заводите» —
 * поручение, документ или процесс по шаблону. Это тот же вопрос, что задаёт
 * Directum RX своей кнопкой «Создать», и он честнее, чем два разных экрана: у
 * документа своя регистрация и номенклатура, у поручения — маршрут и срок, и
 * притвориться, что это одно и то же, нельзя.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { FileText, ListChecks, Loader2, Play, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useCompany } from '@/contexts/CompanyContext'
import * as docsService from '@/services/docsService'
import { NewDocDialog } from '@/components/docs/NewDocDialog'
import { NewTaskDialog } from '@/components/tasks/NewTaskDialog'

export function NewWorkButton() {
  const { company } = useCompany()
  const navigate = useNavigate()
  const companyId = company?.id ?? ''
  const [taskSignal, setTaskSignal] = useState(0)
  const [docOpen, setDocOpen] = useState(false)

  const qc = useQueryClient()

  // Виды документов нужны только для формы документа: спрашиваем их, когда
  // человек этот пункт выбрал, а не при каждой отрисовке шапки.
  const kindsQ = useQuery({
    queryKey: ['doc-kinds', companyId],
    queryFn: () => docsService.listKinds(companyId),
    enabled: docOpen && !!companyId,
  })
  // Шаблоны — то, чем работу заводят чаще всего: «Закрытие месяца», «Заявка на
  // доступ». Держать их за двумя переходами (меню → регламент → кнопка) значит
  // не пользоваться ими вовсе.
  const templatesQ = useQuery({
    queryKey: ['process-templates', companyId],
    queryFn: () => docsService.listProcessTemplates(companyId),
    enabled: !!companyId, staleTime: 5 * 60 * 1000,
  })
  const start = useMutation({
    mutationFn: (template: docsService.ProcessTemplate) =>
      docsService.startProcessTemplate(template.id, companyId),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ['work'] })
      void qc.invalidateQueries({ queryKey: ['work-mine'] })
      // Заведённое открываем сразу: человек нажал «завести», а не «положить в
      // список» — ему нужно дописать предмет и отправить.
      navigate(result.kind === 'document'
        ? `/docs?view=all&doc=${result.docId}`
        : `/docs/company?view=errands&task=${result.taskId}`)
    },
    onError: (e) => toast.error((e as Error).message),
  })

  // В меню — то, что запускается одним нажатием. Шаблон, которому нужны стороны
  // и предмет, ведёт в «Регламент»: спрашивать их из выпадающего меню — значит
  // строить в нём вторую форму.
  const ready = (templatesQ.data?.templates ?? [])
    .filter((t) => !t.requiresPreparation)
    .slice(0, 5)

  if (!companyId) return null
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" className="h-8">
            <Plus className="mr-1.5 h-3.5 w-3.5" />Создать
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-[260px]">
          <DropdownMenuLabel className="text-[11px] font-normal text-muted-foreground">
            Что заводим
          </DropdownMenuLabel>
          <DropdownMenuItem onSelect={() => setTaskSignal((n) => n + 1)}>
            <ListChecks className="mr-2 h-3.5 w-3.5" />
            <span className="flex-1">Поручение</span>
            <span className="text-[10px] text-muted-foreground">N</span>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setDocOpen(true)}>
            <FileText className="mr-2 h-3.5 w-3.5" />
            Документ
          </DropdownMenuItem>
          {ready.length > 0 && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuLabel className="text-[11px] font-normal text-muted-foreground">
                По шаблону
              </DropdownMenuLabel>
              {ready.map((template) => (
                <DropdownMenuItem key={template.id} disabled={start.isPending}
                  onSelect={() => start.mutate(template)}>
                  {start.isPending
                    ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                    : <Play className="mr-2 h-3.5 w-3.5" />}
                  <span className="flex-1 truncate">{template.name}</span>
                  <span className="ml-2 shrink-0 text-[10px] text-muted-foreground">
                    {template.kind === 'document' ? 'документ' : 'поручение'}
                  </span>
                </DropdownMenuItem>
              ))}
            </>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => navigate('/docs/regulation?view=templates')}>
            <Play className="mr-2 h-3.5 w-3.5" />
            <span className="flex-1">Все шаблоны</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Диалог поручения всегда в разметке: он открывается сигналом — и от
          кнопки, и от клавиши `N` на списке. */}
      <div className="hidden">
        <NewTaskDialog companyId={companyId} openSignal={taskSignal}
          onCreated={(id) => navigate(`/docs/company?view=errands&task=${id}`)} />
      </div>
      {docOpen && (
        <NewDocDialog companyId={companyId} kinds={kindsQ.data ?? []}
          onClose={() => setDocOpen(false)}
          onCreated={(id) => { setDocOpen(false); navigate(`/docs?view=all&doc=${id}`) }} />
      )}
    </>
  )
}
